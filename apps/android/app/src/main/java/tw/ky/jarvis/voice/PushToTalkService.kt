package tw.ky.jarvis.voice

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import tw.ky.jarvis.MainActivity
import tw.ky.jarvis.R
import tw.ky.jarvis.network.MobileChannelClient
import tw.ky.jarvis.security.TokenVault
import java.io.ByteArrayOutputStream
import kotlin.concurrent.thread

class PushToTalkService : Service() {
    private var recorder: AudioRecord? = null
    private var captureThread: Thread? = null
    private var audioFocus: AudioFocusRequest? = null
    private var audioBuffer: ByteArrayOutputStream? = null

    @Volatile private var recording = false
    var frameSink: VoiceFrameSink = VoiceFrameSink.DISCARD

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int,
    ): Int {
        when (intent?.action) {
            ACTION_START -> startUserInitiatedCapture()
            ACTION_STOP -> stopCapture(submit = true)
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopCapture(submit = false)
        super.onDestroy()
    }

    private fun startUserInitiatedCapture() {
        if (recording || ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            stopSelf()
            return
        }
        val notification = recordingNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            startMicrophoneForeground(notification)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        requestAudioFocus()
        val minimum =
            AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
        if (minimum <= 0) {
            stopCapture(submit = false)
            stopSelf()
            return
        }
        audioBuffer = ByteArrayOutputStream()
        recorder =
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                minimum * 2,
            ).also { it.startRecording() }
        recording = true
        captureThread =
            thread(name = "ky-jarvis-ptt", isDaemon = true) {
                val buffer = ByteArray(minimum)
                while (recording) {
                    val count = recorder?.read(buffer, 0, buffer.size) ?: break
                    if (count > 0) {
                        val output = audioBuffer
                        if (output != null && output.size() + count <= MAX_PCM_BYTES) {
                            output.write(buffer, 0, count)
                        } else {
                            recording = false
                        }
                        frameSink.onFrame(buffer.copyOf(count))
                    }
                }
                buffer.fill(0)
            }
    }

    private fun stopCapture(submit: Boolean) {
        recording = false
        runCatching { recorder?.stop() }
        recorder?.release()
        recorder = null
        captureThread?.join(500)
        captureThread = null
        abandonAudioFocus()
        stopForeground(STOP_FOREGROUND_REMOVE)
        val pcm16 = audioBuffer?.toByteArray() ?: ByteArray(0)
        audioBuffer?.reset()
        audioBuffer = null
        if (submit && pcm16.size >= MIN_PCM_BYTES) {
            submitVoiceTurn(pcm16)
        } else {
            pcm16.fill(0)
            if (submit) broadcastVoiceError("錄音太短，請按住後再說話")
            stopSelf()
        }
    }

    private fun requestAudioFocus() {
        val manager = getSystemService(AUDIO_SERVICE) as AudioManager
        val request =
            AudioFocusRequest
                .Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
                .setAudioAttributes(
                    AudioAttributes
                        .Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build(),
                ).setOnAudioFocusChangeListener { change ->
                    if (shouldStopForAudioFocusChange(change)) {
                        stopCapture(submit = false)
                        stopSelf()
                    }
                }.build()
        manager.requestAudioFocus(request)
        audioFocus = request
    }

    private fun abandonAudioFocus() {
        val request = audioFocus ?: return
        (getSystemService(AUDIO_SERVICE) as AudioManager).abandonAudioFocusRequest(request)
        audioFocus = null
    }

    private fun createChannel() {
        val channel =
            NotificationChannel(
                CHANNEL_ID,
                "KY-JARVIS 麥克風",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply { description = "顯示使用者啟動的按住說話狀態" }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    @androidx.annotation.RequiresApi(Build.VERSION_CODES.R)
    private fun startMicrophoneForeground(notification: Notification) {
        startForeground(
            NOTIFICATION_ID,
            notification,
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
        )
    }

    private fun recordingNotification(): Notification {
        val stopIntent =
            PendingIntent.getService(
                this,
                1,
                Intent(this, PushToTalkService::class.java).setAction(ACTION_STOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        val openIntent =
            PendingIntent.getActivity(
                this,
                2,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        return NotificationCompat
            .Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentTitle("KY-JARVIS 正在聆聽")
            .setContentText("放開按鈕或點選停止即可關閉麥克風")
            .setContentIntent(openIntent)
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_SECRET)
            .addAction(0, "停止", stopIntent)
            .build()
    }

    @Suppress("TooGenericExceptionCaught")
    private fun submitVoiceTurn(pcm16: ByteArray) {
        thread(name = "ky-jarvis-voice-upload", isDaemon = false) {
            try {
                val result =
                    MobileChannelClient(
                        baseUrl = tw.ky.jarvis.BuildConfig.CORE_BASE_URL,
                        vault = TokenVault(this),
                    ).sendVoiceTurn(pcm16)
                sendBroadcast(
                    Intent(ACTION_VOICE_RESULT)
                        .setPackage(packageName)
                        .putExtra(EXTRA_TRANSCRIPT, result.transcript)
                        .putExtra(EXTRA_SUMMARY, result.reply.summary)
                        .putExtra(EXTRA_REQUIRES_APPROVAL, result.reply.requiresApproval),
                )
            } catch (exc: Exception) {
                broadcastVoiceError(exc.message ?: "本機語音處理失敗")
            } finally {
                pcm16.fill(0)
                stopSelf()
            }
        }
    }

    private fun broadcastVoiceError(message: String) {
        sendBroadcast(
            Intent(ACTION_VOICE_RESULT)
                .setPackage(packageName)
                .putExtra(EXTRA_ERROR, message),
        )
    }

    companion object {
        const val ACTION_START = "tw.ky.jarvis.action.PTT_START"
        const val ACTION_STOP = "tw.ky.jarvis.action.PTT_STOP"
        const val ACTION_VOICE_RESULT = "tw.ky.jarvis.action.VOICE_RESULT"
        const val EXTRA_TRANSCRIPT = "transcript"
        const val EXTRA_SUMMARY = "summary"
        const val EXTRA_REQUIRES_APPROVAL = "requires_approval"
        const val EXTRA_ERROR = "error"
        private const val CHANNEL_ID = "ky_jarvis_microphone"
        private const val NOTIFICATION_ID = 1101
        private const val SAMPLE_RATE = 16_000
        private const val MAX_PCM_BYTES = SAMPLE_RATE * 2 * 30
        private const val MIN_PCM_BYTES = SAMPLE_RATE / 5 * 2

        internal fun shouldStopForAudioFocusChange(change: Int): Boolean = change < 0
    }
}
