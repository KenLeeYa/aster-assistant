package tw.ky.jarvis.worker

import java.time.Duration
import java.time.Instant

enum class WorkerState { ONLINE, DEGRADED, OFFLINE }

data class OfflineEnvelope(
    val id: String,
    val createdAt: Instant,
    val expiresAt: Instant,
    val consequential: Boolean,
    val encryptedPayload: ByteArray,
    val approvalHash: String?,
)

enum class DispatchDecision { SEND, REQUIRE_FRESH_APPROVAL, EXPIRED, KEEP_AS_DRAFT }

object OfflineDispatchPolicy {
    fun decide(
        envelope: OfflineEnvelope,
        state: WorkerState,
        now: Instant,
    ): DispatchDecision {
        if (!now.isBefore(envelope.expiresAt)) return DispatchDecision.EXPIRED
        if (state != WorkerState.ONLINE) return DispatchDecision.KEEP_AS_DRAFT
        if (envelope.consequential &&
            (
                envelope.approvalHash.isNullOrBlank() || Duration.between(envelope.createdAt, now) >
                    Duration.ofMinutes(5)
            )
        ) {
            return DispatchDecision.REQUIRE_FRESH_APPROVAL
        }
        return DispatchDecision.SEND
    }

    fun successMessage(state: WorkerState): String = if (state == WorkerState.ONLINE) "worker 可執行" else "尚未執行：worker 離線"
}
