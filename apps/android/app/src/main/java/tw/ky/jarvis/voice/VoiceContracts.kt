package tw.ky.jarvis.voice

enum class TranscriptState { PARTIAL, FINAL, ABANDONED }

data class TranscriptEvent(
    val turnId: String,
    val text: String,
    val confidence: Double,
    val state: TranscriptState,
)

interface SpeechToTextProvider {
    fun acceptPcm16(frame: ByteArray)

    fun finish(): TranscriptEvent

    fun cancel()
}

interface TextToSpeechProvider {
    fun speak(text: String)

    fun stop()
}

object TranscriptPolicy {
    @Suppress("MaxLineLength")
    fun mayPromoteToMemory(event: TranscriptEvent): Boolean = event.state == TranscriptState.FINAL && event.text.isNotBlank()

    fun requiresVisualConfirmation(
        event: TranscriptEvent,
        consequential: Boolean,
    ): Boolean = consequential && (event.state != TranscriptState.FINAL || event.confidence < 0.80)
}

/** Raw PCM is consumed in memory only. The default implementation never persists it. */
fun interface VoiceFrameSink {
    fun onFrame(frame: ByteArray)

    companion object {
        val DISCARD = VoiceFrameSink { frame -> frame.fill(0) }
    }
}
