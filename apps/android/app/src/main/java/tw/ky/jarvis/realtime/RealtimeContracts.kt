package tw.ky.jarvis.realtime

enum class RealtimeMode { MOCK, CHAINED_LOCAL, WEBRTC }

data class RealtimeEvent(
    val type: String,
    val payload: Map<String, String>,
    val version: Int = EventCodec.VERSION,
)

interface RealtimeTransport {
    val mode: RealtimeMode

    fun connect(ephemeralClientSecret: String? = null)

    fun send(event: RealtimeEvent)

    fun close()
}

class MockRealtimeTransport : RealtimeTransport {
    override val mode = RealtimeMode.MOCK
    val sent = mutableListOf<RealtimeEvent>()
    var connected = false
        private set

    override fun connect(ephemeralClientSecret: String?) {
        require(ephemeralClientSecret == null) { "mock transport does not accept credentials" }
        connected = true
    }

    override fun send(event: RealtimeEvent) {
        check(connected)
        EventCodec.validate(event)
        sent += event
    }

    override fun close() {
        connected = false
    }
}

class ChainedLocalRealtimeTransport(
    private val relayToCore: (RealtimeEvent) -> Unit,
) : RealtimeTransport {
    override val mode = RealtimeMode.CHAINED_LOCAL
    private var connected = false

    override fun connect(ephemeralClientSecret: String?) {
        require(ephemeralClientSecret == null) { "local fallback never accepts provider secrets" }
        connected = true
    }

    override fun send(event: RealtimeEvent) {
        check(connected)
        EventCodec.validate(event)
        relayToCore(event)
    }

    override fun close() {
        connected = false
    }
}

object EventCodec {
    const val VERSION = 1
    private val allowedTypes =
        setOf(
            "input_audio_buffer.append",
            "input_audio_buffer.commit",
            "conversation.item.create",
            "response.create",
            "response.audio.delta",
            "response.audio_transcript.delta",
            "response.done",
            "error",
        )
    private val allowedIntents = setOf("chat", "agenda", "project_status", "approval_review")

    fun validate(event: RealtimeEvent) {
        require(event.version == VERSION) { "unsupported Realtime event version" }
        require(event.type in allowedTypes) { "event type is not allowlisted" }
        require(
            event.payload.keys.none { key ->
                key.contains("api_key", ignoreCase = true) ||
                    key.contains("mcp", ignoreCase = true) ||
                    key.contains("tool", ignoreCase = true)
            },
        ) { "event cannot carry reusable credentials or direct tool routing" }
        event.payload["intent"]?.let { intent ->
            require(intent in allowedIntents) { "intent must return to an allowlisted Core route" }
        }
    }
}

interface WebRtcPeerAdapter {
    fun connect(ephemeralClientSecret: String)

    fun send(event: RealtimeEvent)

    fun close()
}

class BlockedWebRtcPeerAdapter : WebRtcPeerAdapter {
    override fun connect(ephemeralClientSecret: String) {
        require(ephemeralClientSecret.isNotBlank())
        throw UnsupportedOperationException(
            "live WebRTC peer is blocked pending credential authorization",
        )
    }

    override fun send(event: RealtimeEvent) = error("live WebRTC peer is not connected")

    override fun close() = Unit
}

class WebRtcRealtimeTransport(
    private val peer: WebRtcPeerAdapter = BlockedWebRtcPeerAdapter(),
) : RealtimeTransport {
    override val mode = RealtimeMode.WEBRTC
    private var connected = false

    override fun connect(ephemeralClientSecret: String?) {
        require(!ephemeralClientSecret.isNullOrBlank()) { "ephemeral client secret required" }
        require(!ephemeralClientSecret.startsWith("sk-")) { "standard API keys are forbidden" }
        peer.connect(ephemeralClientSecret)
        connected = true
    }

    override fun send(event: RealtimeEvent) {
        check(connected)
        EventCodec.validate(event)
        peer.send(event)
    }

    override fun close() {
        peer.close()
        connected = false
    }
}
