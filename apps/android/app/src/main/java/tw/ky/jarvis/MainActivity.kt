package tw.ky.jarvis

import android.Manifest
import android.app.role.RoleManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.tts.TextToSpeech
import android.util.Base64
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import tw.ky.jarvis.network.CoreApiClient
import tw.ky.jarvis.network.MobileAgendaSummary
import tw.ky.jarvis.network.MobileApprovalRequest
import tw.ky.jarvis.network.MobileChannelClient
import tw.ky.jarvis.network.MobileCommand
import tw.ky.jarvis.network.MobileHeartbeat
import tw.ky.jarvis.network.MobileProjectSummary
import tw.ky.jarvis.network.MobileReply
import tw.ky.jarvis.network.PairingClient
import tw.ky.jarvis.network.PairingPayload
import tw.ky.jarvis.security.ApprovalSigner
import tw.ky.jarvis.security.ApprovalToSign
import tw.ky.jarvis.security.DeviceKeyStore
import tw.ky.jarvis.security.TokenVault
import tw.ky.jarvis.ui.JarvisApp
import tw.ky.jarvis.voice.PushToTalkService
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

private data class MobileWorkspaceSnapshot(
    val heartbeat: MobileHeartbeat,
    val commands: List<MobileCommand>,
    val projects: List<MobileProjectSummary>,
    val agenda: List<MobileAgendaSummary>,
    val approvals: List<MobileApprovalRequest>,
)

class MainActivity : FragmentActivity() {
    private var pairingPayload by mutableStateOf<PairingPayload?>(null)
    private var pairingStatus by mutableStateOf("尚未收到配對連結")
    private var assistantStatus by mutableStateOf("正在檢查目前預設助理")
    private var mobileStatus by mutableStateOf("等待安全 channel 同步")
    private var latestCommand by mutableStateOf<MobileCommand?>(null)
    private var conversationStatus by mutableStateOf("可傳送文字到本機模型")
    private var conversationReply by mutableStateOf<MobileReply?>(null)
    private var mobileProjects by mutableStateOf<List<MobileProjectSummary>>(emptyList())
    private var mobileAgenda by mutableStateOf<List<MobileAgendaSummary>>(emptyList())
    private var mobileApprovals by mutableStateOf<List<MobileApprovalRequest>>(emptyList())
    private var approvalStatus by mutableStateOf("高風險動作必須以強式生物辨識簽章")
    private var textToSpeech: TextToSpeech? = null
    private var textToSpeechReady = false
    private val voiceResultReceiver =
        object : BroadcastReceiver() {
            override fun onReceive(
                context: Context?,
                intent: Intent?,
            ) {
                val error = intent?.getStringExtra(PushToTalkService.EXTRA_ERROR)
                if (error != null) {
                    conversationStatus = error
                    return
                }
                val transcript = intent?.getStringExtra(PushToTalkService.EXTRA_TRANSCRIPT) ?: return
                val summary = intent.getStringExtra(PushToTalkService.EXTRA_SUMMARY).orEmpty()
                conversationStatus = "語音轉錄：$transcript"
                conversationReply =
                    MobileReply(
                        summary = summary,
                        steps = emptyList(),
                        requiresApproval =
                            intent.getBooleanExtra(
                                PushToTalkService.EXTRA_REQUIRES_APPROVAL,
                                false,
                            ),
                        route = "voice",
                    )
                if (textToSpeechReady && summary.isNotBlank()) {
                    textToSpeech?.speak(summary, TextToSpeech.QUEUE_FLUSH, null, "voice-turn")
                }
            }
        }
    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }
    private val assistantSettingsLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
            refreshAssistantStatus()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        acceptPairingIntent(intent)
        ContextCompat.registerReceiver(
            this,
            voiceResultReceiver,
            IntentFilter(PushToTalkService.ACTION_VOICE_RESULT),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        textToSpeech =
            TextToSpeech(this) { status ->
                if (status == TextToSpeech.SUCCESS) {
                    textToSpeechReady = (textToSpeech?.setLanguage(Locale.TAIWAN) ?: -1) >=
                        TextToSpeech.LANG_AVAILABLE
                }
            }
        window.setFlags(
            android.view.WindowManager.LayoutParams.FLAG_SECURE,
            android.view.WindowManager.LayoutParams.FLAG_SECURE,
        )
        setContent {
            JarvisApp(
                coreBaseUrl = BuildConfig.CORE_BASE_URL,
                onRefreshWorker = { callback -> refreshWorker(callback) },
                onPushToTalk = ::setPushToTalk,
                assistantStatus = assistantStatus,
                onOpenAssistantSettings = ::openAssistantSettings,
                pairingPayload = pairingPayload,
                pairingStatus = pairingStatus,
                onCompletePairing = ::completePairing,
                onClaimPairing = ::claimPairing,
                mobileStatus = mobileStatus,
                latestCommand = latestCommand,
                conversationStatus = conversationStatus,
                conversationReply = conversationReply,
                onSyncMobile = { syncMobileChannel(silent = false) },
                onCommandDisplayed = ::acknowledgeDisplayedCommand,
                onSendMessage = ::sendMobileMessage,
                projects = mobileProjects,
                agenda = mobileAgenda,
                approvals = mobileApprovals,
                approvalStatus = approvalStatus,
                onApprovalDecision = ::decideMobileApproval,
            )
        }
        if (TokenVault(this).get("access_token") != null && pairingPayload == null) {
            pairingStatus = "此手機已有 Keystore 保護的安全 session"
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (isActive) {
                    if (TokenVault(this@MainActivity).get("access_token") != null) {
                        syncMobileChannelOnce(silent = true)
                    }
                    delay(MOBILE_POLL_INTERVAL_MS)
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshAssistantStatus()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        acceptPairingIntent(intent)
    }

    override fun onDestroy() {
        unregisterReceiver(voiceResultReceiver)
        textToSpeech?.stop()
        textToSpeech?.shutdown()
        textToSpeech = null
        super.onDestroy()
    }

    private fun acceptPairingIntent(intent: Intent) {
        val uri = intent.data ?: return
        runCatching { PairingPayload.fromUri(uri.toString()) }
            .onSuccess {
                pairingPayload = it
                pairingStatus = "請比對桌面與手機上的六位數代碼"
            }.onFailure { pairingStatus = it.message ?: "配對連結無效" }
        intent.data = null
    }

    private fun refreshWorker(callback: (Boolean) -> Unit) {
        lifecycleScope.launch {
            val online =
                withContext(Dispatchers.IO) {
                    val vault = TokenVault(this@MainActivity)
                    if (vault.get("access_token") == null) {
                        CoreApiClient(BuildConfig.CORE_BASE_URL).isWorkerReady()
                    } else {
                        runCatching {
                            MobileChannelClient(
                                BuildConfig.CORE_BASE_URL,
                                vault,
                            ).workerPresence().state == "online"
                        }.getOrDefault(false)
                    }
                }
            callback(online)
        }
    }

    private fun setPushToTalk(active: Boolean) {
        if (active && !hasMicrophonePermission()) {
            val requested = mutableListOf(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                requested += Manifest.permission.POST_NOTIFICATIONS
            }
            permissionLauncher.launch(requested.toTypedArray())
            return
        }
        val intent =
            Intent(this, PushToTalkService::class.java).setAction(
                if (active) PushToTalkService.ACTION_START else PushToTalkService.ACTION_STOP,
            )
        if (active) {
            ContextCompat.startForegroundService(this, intent)
        } else {
            startService(intent)
        }
    }

    private fun hasMicrophonePermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun openAssistantSettings() {
        val intent =
            listOf(
                Intent(Settings.ACTION_VOICE_INPUT_SETTINGS),
                Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS),
            ).firstOrNull { it.resolveActivity(packageManager) != null }

        if (intent == null) {
            assistantStatus = "找不到 Android 預設助理設定頁面"
            return
        }

        assistantStatus = "已開啟 Android 系統頁面；請選擇 KY-JARVIS"
        runCatching { assistantSettingsLauncher.launch(intent) }
            .onFailure { assistantStatus = "無法開啟 Android 預設助理設定頁面" }
    }

    private fun refreshAssistantStatus() {
        val manager = getSystemService(RoleManager::class.java)
        assistantStatus =
            when {
                !manager.isRoleAvailable(RoleManager.ROLE_ASSISTANT) -> {
                    "此裝置未提供 Android 預設助理角色"
                }

                manager.isRoleHeld(RoleManager.ROLE_ASSISTANT) -> {
                    "KY-JARVIS 已是目前的預設助理"
                }

                else -> {
                    "目前預設助理仍是其他應用程式"
                }
            }
    }

    private fun completePairing(payload: PairingPayload) {
        lifecycleScope.launch {
            val result =
                withContext(Dispatchers.IO) {
                    runCatching {
                        PairingClient(
                            BuildConfig.CORE_BASE_URL,
                            DeviceKeyStore(),
                            TokenVault(this@MainActivity),
                        ).complete(payload)
                    }
                }
            pairingStatus =
                result.fold(
                    onSuccess = { "裝置已送交桌面確認；請在桌面核對 ${it.comparisonCode}" },
                    onFailure = { it.message ?: "送交配對失敗" },
                )
        }
    }

    private fun claimPairing(payload: PairingPayload) {
        lifecycleScope.launch {
            val result =
                withContext(Dispatchers.IO) {
                    runCatching {
                        PairingClient(
                            BuildConfig.CORE_BASE_URL,
                            DeviceKeyStore(),
                            TokenVault(this@MainActivity),
                        ).claim(payload)
                    }
                }
            pairingStatus =
                result.fold(
                    onSuccess = {
                        pairingPayload = null
                        syncMobileChannel(silent = false)
                        "配對完成；token 僅保存於 Android Keystore 加密 vault"
                    },
                    onFailure = { it.message ?: "尚未完成桌面確認" },
                )
        }
    }

    private fun syncMobileChannel(silent: Boolean) {
        lifecycleScope.launch { syncMobileChannelOnce(silent) }
    }

    private suspend fun syncMobileChannelOnce(silent: Boolean) {
        val result =
            withContext(Dispatchers.IO) {
                runCatching {
                    val client =
                        MobileChannelClient(
                            BuildConfig.CORE_BASE_URL,
                            TokenVault(this@MainActivity),
                        )
                    MobileWorkspaceSnapshot(
                        heartbeat = client.heartbeat(),
                        commands = client.pendingCommands(),
                        projects = client.projects(),
                        agenda = client.agenda(),
                        approvals = client.approvals(),
                    )
                }
            }
        result
            .onSuccess { snapshot ->
                snapshot.commands.lastOrNull()?.let { latestCommand = it }
                mobileProjects = snapshot.projects
                mobileAgenda = snapshot.agenda
                mobileApprovals = snapshot.approvals
                mobileStatus =
                    if (snapshot.commands.isEmpty()) {
                        "安全 channel 在線；待處理 ${snapshot.heartbeat.pendingCount} 筆"
                    } else {
                        "已從 Windows 收到 ${snapshot.commands.size} 筆訊息"
                    }
            }.onFailure {
                if (!silent || mobileStatus.contains("在線")) {
                    mobileStatus = it.message ?: "安全 channel 同步失敗"
                }
            }
    }

    private fun acknowledgeDisplayedCommand(commandId: java.util.UUID) {
        lifecycleScope.launch {
            val result =
                withContext(Dispatchers.IO) {
                    runCatching {
                        MobileChannelClient(
                            BuildConfig.CORE_BASE_URL,
                            TokenVault(this@MainActivity),
                        ).acknowledge(commandId)
                    }
                }
            result
                .onSuccess { mobileStatus = "手機已顯示訊息並回傳回執" }
                .onFailure { mobileStatus = it.message ?: "訊息回執失敗" }
        }
    }

    private fun sendMobileMessage(message: String) {
        conversationStatus = "本機模型處理中…"
        lifecycleScope.launch {
            val result =
                withContext(Dispatchers.IO) {
                    runCatching {
                        MobileChannelClient(
                            BuildConfig.CORE_BASE_URL,
                            TokenVault(this@MainActivity),
                        ).sendMessage(message)
                    }
                }
            result
                .onSuccess {
                    conversationReply = it
                    conversationStatus = "本機模型已回覆"
                }.onFailure {
                    conversationStatus = it.message ?: "本機模型回覆失敗"
                }
        }
    }

    private fun decideMobileApproval(
        approval: MobileApprovalRequest,
        approved: Boolean,
    ) {
        val deviceId = TokenVault(this).get("device_id")?.let(UUID::fromString)
        if (deviceId == null) {
            approvalStatus = "手機尚未完成安全配對"
            return
        }
        val decision = if (approved) "approve" else "deny"
        val timestamp = OffsetDateTime.now(ZoneOffset.UTC).format(APPROVAL_TIME_FORMAT)
        val request =
            ApprovalToSign(
                approvalId = approval.id,
                actionHash = approval.actionHash,
                nonce = approval.nonce,
                decision = decision,
                deviceId = deviceId,
                timestampIso = timestamp,
            )
        approvalStatus = "等待強式生物辨識確認"
        ApprovalSigner(this).authenticateAndSign(
            request,
            onSigned = { signature ->
                lifecycleScope.launch {
                    val result =
                        withContext(Dispatchers.IO) {
                            runCatching {
                                MobileChannelClient(
                                    BuildConfig.CORE_BASE_URL,
                                    TokenVault(this@MainActivity),
                                ).decideApproval(
                                    approval.id,
                                    decision,
                                    timestamp,
                                    Base64.encodeToString(signature, Base64.NO_WRAP),
                                )
                            }
                        }
                    signature.fill(0)
                    result
                        .onSuccess {
                            approvalStatus =
                                if (it.executed) {
                                    "核准已驗證並執行；狀態 ${it.state}"
                                } else {
                                    "核准決策已驗證；狀態 ${it.state}"
                                }
                            syncMobileChannel(silent = true)
                        }.onFailure {
                            approvalStatus = it.message ?: "核准簽章送出失敗"
                        }
                }
            },
            onError = { approvalStatus = "生物辨識未完成：$it" },
        )
    }

    companion object {
        private const val MOBILE_POLL_INTERVAL_MS = 5_000L
        private val APPROVAL_TIME_FORMAT =
            DateTimeFormatter.ofPattern(
                "yyyy-MM-dd'T'HH:mm:ssxxx",
            )
    }
}
