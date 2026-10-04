package tw.ky.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import tw.ky.jarvis.network.PairingPayload
import tw.ky.jarvis.realtime.ChainedLocalRealtimeTransport
import tw.ky.jarvis.realtime.EventCodec
import tw.ky.jarvis.realtime.MockRealtimeTransport
import tw.ky.jarvis.realtime.RealtimeEvent
import tw.ky.jarvis.realtime.WebRtcPeerAdapter
import tw.ky.jarvis.realtime.WebRtcRealtimeTransport
import tw.ky.jarvis.security.Payloads
import tw.ky.jarvis.voice.PushToTalkService
import tw.ky.jarvis.voice.TranscriptEvent
import tw.ky.jarvis.voice.TranscriptPolicy
import tw.ky.jarvis.voice.TranscriptState
import tw.ky.jarvis.worker.DispatchDecision
import tw.ky.jarvis.worker.OfflineDispatchPolicy
import tw.ky.jarvis.worker.OfflineEnvelope
import tw.ky.jarvis.worker.WorkerState
import java.time.Instant
import java.util.UUID

class SecurityContractsTest {
    @Test
    fun debugCoreEndpointUsesUsbLoopbackBridge() {
        assertEquals("http://127.0.0.1:8765", BuildConfig.CORE_BASE_URL)
    }

    @Test
    fun pairingChallengeMatchesServerContract() {
        val id = UUID.fromString("a4b86db4-157c-4ab2-9fee-a979c17e2839")
        assertEquals(
            "ky-jarvis-pairing-v1:$id:one-time-secret",
            Payloads.pairing(id, "one-time-secret").decodeToString(),
        )
    }

    @Test
    fun pairingUriIsStrictAndExpiring() {
        val payload =
            PairingPayload.fromUri(
                "kyjarvis://pair?session_id=a4b86db4-157c-4ab2-9fee-a979c17e2839" +
                    "&secret=${"s".repeat(32)}&comparison_code=123456" +
                    "&fingerprint=sha256%3Atest&expires_at=2099-09-01T00%3A00%3A00Z",
            )
        assertEquals("123456", payload.comparisonCode)
        assertThrows(IllegalArgumentException::class.java) {
            PairingPayload.fromUri("https://attacker.invalid/pair?secret=${"s".repeat(32)}")
        }
    }

    @Test
    fun approvalPayloadPreservesServerIsoTimestamp() {
        val approval = UUID.fromString("fb341be8-a21d-4240-942b-f23cd13bde8f")
        val device = UUID.fromString("e28741d9-a141-4e9d-8547-e3a9616ced38")
        val payload =
            Payloads
                .approval(
                    approval,
                    "a".repeat(64),
                    "nonce",
                    "approve",
                    device,
                    "2026-09-01T00:00:00+00:00",
                ).decodeToString()
        assertEquals(
            "ky-jarvis-approval-v1:$approval:${"a".repeat(64)}:nonce:approve:$device:" +
                "2026-09-01T00:00:00+00:00",
            payload,
        )
    }

    @Test
    fun realtimeCodecRejectsDirectToolAndApiKeyRouting() {
        assertThrows(IllegalArgumentException::class.java) {
            EventCodec.validate(RealtimeEvent("tool.call", emptyMap()))
        }
        assertThrows(IllegalArgumentException::class.java) {
            EventCodec.validate(
                RealtimeEvent("response.create", mapOf("mcp_tool" to "filesystem.write")),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            EventCodec.validate(
                RealtimeEvent("response.create", mapOf("api_key" to "forbidden")),
            )
        }
    }

    @Test
    fun mockRealtimeWorksWithoutCredentials() {
        val transport = MockRealtimeTransport()
        transport.connect()
        transport.send(RealtimeEvent("response.create", mapOf("intent" to "chat")))
        assertEquals(1, transport.sent.size)
        transport.close()
    }

    @Test
    fun realtimeUsesVersionedNarrowIntentsAndSafeLocalFallback() {
        val relayed = mutableListOf<RealtimeEvent>()
        val fallback = ChainedLocalRealtimeTransport { event -> relayed += event }
        fallback.connect()
        fallback.send(RealtimeEvent("response.create", mapOf("intent" to "chat")))
        assertEquals(1, relayed.size)
        assertThrows(IllegalArgumentException::class.java) {
            fallback.send(RealtimeEvent("response.create", mapOf("intent" to "tool_execute")))
        }
        assertThrows(IllegalArgumentException::class.java) {
            EventCodec.validate(RealtimeEvent("response.create", emptyMap(), version = 2))
        }
        fallback.close()
    }

    @Test
    fun webRtcBoundaryAcceptsOnlyEphemeralSecrets() {
        val sent = mutableListOf<RealtimeEvent>()
        var connectedSecret: String? = null
        val peer =
            object : WebRtcPeerAdapter {
                override fun connect(ephemeralClientSecret: String) {
                    connectedSecret = ephemeralClientSecret
                }

                override fun send(event: RealtimeEvent) {
                    sent += event
                }

                override fun close() = Unit
            }
        val transport = WebRtcRealtimeTransport(peer)
        assertThrows(IllegalArgumentException::class.java) { transport.connect("sk-reusable") }
        transport.connect("ek_ephemeral_contract")
        transport.send(RealtimeEvent("response.create", mapOf("intent" to "chat")))
        assertEquals("ek_ephemeral_contract", connectedSecret)
        assertEquals(1, sent.size)
        transport.close()
    }

    @Test
    fun staleConsequentialEnvelopeRequiresFreshApproval() {
        val now = Instant.parse("2026-09-01T00:10:00Z")
        val envelope =
            OfflineEnvelope(
                id = "cmd-1",
                createdAt = now.minusSeconds(360),
                expiresAt = now.plusSeconds(600),
                consequential = true,
                encryptedPayload = byteArrayOf(1),
                approvalHash = "approved-before-going-offline",
            )
        assertEquals(
            DispatchDecision.REQUIRE_FRESH_APPROVAL,
            OfflineDispatchPolicy.decide(envelope, WorkerState.ONLINE, now),
        )
        assertEquals(
            DispatchDecision.KEEP_AS_DRAFT,
            OfflineDispatchPolicy.decide(envelope, WorkerState.OFFLINE, now),
        )
        assertTrue(OfflineDispatchPolicy.successMessage(WorkerState.OFFLINE).contains("尚未執行"))
    }

    @Test
    fun onlyFinalTranscriptCanBecomeMemory() {
        assertFalse(
            TranscriptPolicy.mayPromoteToMemory(
                TranscriptEvent("turn", "partial", 0.95, TranscriptState.PARTIAL),
            ),
        )
        assertTrue(
            TranscriptPolicy.mayPromoteToMemory(
                TranscriptEvent("turn", "final", 0.95, TranscriptState.FINAL),
            ),
        )
        assertTrue(
            TranscriptPolicy.requiresVisualConfirmation(
                TranscriptEvent("turn", "delete", 0.50, TranscriptState.FINAL),
                consequential = true,
            ),
        )
    }

    @Test
    fun everyAudioFocusLossStopsCapture() {
        assertTrue(PushToTalkService.shouldStopForAudioFocusChange(-1))
        assertTrue(PushToTalkService.shouldStopForAudioFocusChange(-2))
        assertTrue(PushToTalkService.shouldStopForAudioFocusChange(-3))
        assertFalse(PushToTalkService.shouldStopForAudioFocusChange(1))
    }
}
