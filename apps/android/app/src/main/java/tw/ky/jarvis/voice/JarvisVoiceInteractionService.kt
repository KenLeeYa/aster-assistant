package tw.ky.jarvis.voice

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import tw.ky.jarvis.MainActivity
import tw.ky.jarvis.R

class JarvisVoiceInteractionService : VoiceInteractionService()

class JarvisVoiceInteractionSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession = JarvisVoiceInteractionSession(this)
}

class JarvisVoiceInteractionSession(
    context: Context,
) : VoiceInteractionSession(context) {
    override fun onCreateContentView(): View {
        val layout =
            LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(48, 48, 48, 48)
            }
        layout.addView(
            TextView(context).apply {
                setText(R.string.assistant_session_message)
            },
        )
        layout.addView(
            Button(context).apply {
                setText(R.string.open_push_to_talk)
                setOnClickListener {
                    val pending =
                        PendingIntent.getActivity(
                            context,
                            3,
                            Intent(context, MainActivity::class.java),
                            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                        )
                    pending.send()
                    finish()
                }
            },
        )
        return layout
    }
}
