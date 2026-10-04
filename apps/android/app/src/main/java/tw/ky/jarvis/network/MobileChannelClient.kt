package tw.ky.jarvis.network

import org.json.JSONArray
import org.json.JSONObject
import tw.ky.jarvis.security.TokenVault
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.util.UUID

data class MobileCommand(
    val id: UUID,
    val title: String,
    val body: String,
    val state: String,
    val createdAt: Instant,
)

data class MobileReply(
    val summary: String,
    val steps: List<String>,
    val requiresApproval: Boolean,
    val route: String,
)

data class MobileHeartbeat(
    val pendingCount: Int,
    val lastSeenAt: String,
)

data class MobileWorkerPresence(
    val state: String,
    val lastSeenAt: String?,
)

data class MobileProjectSummary(
    val id: UUID,
    val title: String,
    val workItemCount: Int,
    val risks: List<String>,
)

data class MobileAgendaSummary(
    val id: UUID,
    val timezone: String,
    val blocks: List<String>,
    val conflicts: List<String>,
)

data class MobileApprovalRequest(
    val id: UUID,
    val title: String,
    val reason: String,
    val target: String,
    val riskLevel: String,
    val preview: String,
    val permissions: List<String>,
    val sideEffects: List<String>,
    val rollbackMethod: String,
    val actionHash: String,
    val nonce: String,
    val expiresAt: String,
)

data class MobileApprovalOutcome(
    val state: String,
    val executed: Boolean,
)

data class VoiceTurnReply(
    val transcript: String,
    val confidence: Double?,
    val reply: MobileReply,
)

internal fun mobileErrorDetail(
    statusCode: Int,
    text: String,
    fallback: String,
): String {
    if (statusCode == HttpURLConnection.HTTP_UNAUTHORIZED) {
        return "安全 session 已失效，請重新配對"
    }
    return runCatching { JSONObject(text).optString("detail", fallback) }.getOrDefault(fallback)
}

class MobileChannelClient(
    private val baseUrl: String,
    private val vault: TokenVault,
) {
    fun heartbeat(): MobileHeartbeat {
        val response = request("POST", "/api/v1/mobile/heartbeat", JSONObject())
        return MobileHeartbeat(
            pendingCount = response.getInt("pending_count"),
            lastSeenAt = response.getString("last_seen_at"),
        )
    }

    fun pendingCommands(): List<MobileCommand> {
        val response = requestArray("GET", "/api/v1/mobile/commands/pending")
        return buildList {
            for (index in 0 until response.length()) {
                val command = response.getJSONObject(index)
                add(
                    MobileCommand(
                        id = UUID.fromString(command.getString("id")),
                        title = command.getString("title"),
                        body = command.getString("body"),
                        state = command.getString("state"),
                        createdAt = Instant.parse(command.getString("created_at")),
                    ),
                )
            }
        }
    }

    fun workerPresence(): MobileWorkerPresence {
        val response = request("GET", "/api/v1/mobile/worker-presence")
        return MobileWorkerPresence(
            state = response.getString("state"),
            lastSeenAt = response.optString("last_seen_at").ifBlank { null },
        )
    }

    fun projects(): List<MobileProjectSummary> {
        val response = requestArray("GET", "/api/v1/mobile/projects")
        return buildList {
            for (index in 0 until response.length()) {
                val project = response.getJSONObject(index)
                add(
                    MobileProjectSummary(
                        id = UUID.fromString(project.getString("project_id")),
                        title = project.getString("title"),
                        workItemCount = project.optJSONArray("work_items")?.length() ?: 0,
                        risks = stringList(project.optJSONArray("risks")),
                    ),
                )
            }
        }
    }

    fun agenda(): List<MobileAgendaSummary> {
        val response = requestArray("GET", "/api/v1/mobile/agenda")
        return buildList {
            for (index in 0 until response.length()) {
                val proposal = response.getJSONObject(index)
                val blocks = proposal.optJSONArray("blocks") ?: JSONArray()
                add(
                    MobileAgendaSummary(
                        id = UUID.fromString(proposal.getString("id")),
                        timezone = proposal.getString("timezone"),
                        blocks =
                            buildList {
                                for (blockIndex in 0 until blocks.length()) {
                                    val block = blocks.getJSONObject(blockIndex)
                                    add("${block.getString("start")} → ${block.getString("end")}")
                                }
                            },
                        conflicts = stringList(proposal.optJSONArray("conflicts")),
                    ),
                )
            }
        }
    }

    fun approvals(): List<MobileApprovalRequest> {
        val response = requestArray("GET", "/api/v1/mobile/approvals")
        return buildList {
            for (index in 0 until response.length()) {
                val approval = response.getJSONObject(index)
                add(
                    MobileApprovalRequest(
                        id = UUID.fromString(approval.getString("id")),
                        title = approval.getString("title"),
                        reason = approval.getString("reason"),
                        target = approval.getString("target"),
                        riskLevel = approval.getString("risk_level"),
                        preview = approval.getJSONObject("preview").toString(),
                        permissions = stringList(approval.optJSONArray("permissions")),
                        sideEffects = stringList(approval.optJSONArray("side_effects")),
                        rollbackMethod = approval.getString("rollback_method"),
                        actionHash = approval.getString("action_hash"),
                        nonce = approval.getString("nonce"),
                        expiresAt = approval.getString("expires_at"),
                    ),
                )
            }
        }
    }

    fun decideApproval(
        approvalId: UUID,
        decision: String,
        timestamp: String,
        signatureB64: String,
    ): MobileApprovalOutcome {
        require(decision == "approve" || decision == "deny") { "無效核准決策" }
        val response =
            request(
                "POST",
                "/api/v1/mobile/approvals/$approvalId/decision",
                JSONObject()
                    .put("decision", decision)
                    .put("timestamp", timestamp)
                    .put("signature_b64", signatureB64),
            )
        return MobileApprovalOutcome(
            state = response.getJSONObject("approval").getString("state"),
            executed = !response.isNull("result"),
        )
    }

    fun acknowledge(commandId: UUID) {
        request(
            "POST",
            "/api/v1/mobile/commands/$commandId/ack",
            JSONObject().put("receipt", "displayed"),
        )
    }

    fun sendMessage(
        message: String,
        threadId: String = "android-main",
    ): MobileReply {
        require(message.isNotBlank()) { "訊息不可空白" }
        val response =
            request(
                "POST",
                "/api/v1/mobile/messages",
                JSONObject().put("message", message.trim()).put("thread_id", threadId),
            )
        return parseReply(response)
    }

    fun sendVoiceTurn(pcm16: ByteArray): VoiceTurnReply = sendVoiceTurn(pcm16, retry = true)

    private fun sendVoiceTurn(
        pcm16: ByteArray,
        retry: Boolean,
    ): VoiceTurnReply {
        require(pcm16.isNotEmpty() && pcm16.size % 2 == 0) { "錄音資料格式無效" }
        require(pcm16.size <= MAX_VOICE_BYTES) { "單次錄音不可超過 30 秒" }
        val accessToken = requireNotNull(vault.get("access_token")) { "手機尚未完成安全配對" }
        val response =
            executeBytes(
                method = "POST",
                path = "/api/v1/mobile/voice-turns",
                body = pcm16,
                contentType = "application/octet-stream",
                accessToken = accessToken,
                headers =
                    mapOf(
                        "X-Audio-Sample-Rate" to "16000",
                        "X-Audio-Locale" to "zh-TW",
                    ),
                readTimeoutMs = 300_000,
            )
        if (response.code == HttpURLConnection.HTTP_UNAUTHORIZED && retry) {
            refreshSession()
            return sendVoiceTurn(pcm16, retry = false)
        }
        check(response.code in 200..299) {
            mobileErrorDetail(response.code, response.text, "本機語音處理失敗")
        }
        val payload = JSONObject(response.text)
        val transcript = payload.getJSONObject("transcript")
        return VoiceTurnReply(
            transcript = transcript.getString("text"),
            confidence =
                if (transcript.isNull("confidence")) {
                    null
                } else {
                    transcript.getDouble("confidence")
                },
            reply = parseReply(payload.getJSONObject("reply")),
        )
    }

    private fun request(
        method: String,
        path: String,
        body: JSONObject? = null,
        retryAfterRefresh: Boolean = true,
    ): JSONObject =
        JSONObject(
            requestText(method, path, body, retryAfterRefresh),
        )

    private fun requestArray(
        method: String,
        path: String,
        retryAfterRefresh: Boolean = true,
    ): JSONArray = JSONArray(requestText(method, path, null, retryAfterRefresh))

    private fun requestText(
        method: String,
        path: String,
        body: JSONObject?,
        retryAfterRefresh: Boolean,
    ): String {
        require(baseUrl.isNotBlank()) { "Core API 端點尚未設定" }
        val accessToken = requireNotNull(vault.get("access_token")) { "手機尚未完成安全配對" }
        val response = execute(method, path, body, accessToken)
        if (response.code == HttpURLConnection.HTTP_UNAUTHORIZED && retryAfterRefresh) {
            refreshSession()
            return requestText(method, path, body, retryAfterRefresh = false)
        }
        check(response.code in 200..299) {
            mobileErrorDetail(response.code, response.text, "Core 拒絕手機請求")
        }
        return response.text
    }

    private fun refreshSession() {
        val familyId = requireNotNull(vault.get("family_id")) { "缺少 session family" }
        val refreshToken = requireNotNull(vault.get("refresh_token")) { "缺少 refresh token" }
        val response =
            execute(
                "POST",
                "/api/v1/mobile/sessions/refresh",
                JSONObject().put("family_id", familyId).put("refresh_token", refreshToken),
                accessToken = null,
            )
        check(response.code in 200..299) {
            mobileErrorDetail(response.code, response.text, "手機 session 已失效")
        }
        val tokens = JSONObject(response.text)
        vault.put("device_id", tokens.getString("device_id"))
        vault.put("family_id", tokens.getString("family_id"))
        vault.put("access_token", tokens.getString("access_token"))
        vault.put("refresh_token", tokens.getString("refresh_token"))
    }

    private fun execute(
        method: String,
        path: String,
        body: JSONObject?,
        accessToken: String?,
    ): HttpResponse =
        executeBytes(
            method = method,
            path = path,
            body = body?.toString()?.encodeToByteArray(),
            contentType = if (body == null) null else "application/json",
            accessToken = accessToken,
        )

    private fun executeBytes(
        method: String,
        path: String,
        body: ByteArray?,
        contentType: String?,
        accessToken: String?,
        headers: Map<String, String> = emptyMap(),
        readTimeoutMs: Int = 90_000,
    ): HttpResponse {
        val connection = URL("${baseUrl.trimEnd('/')}$path").openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 5_000
        connection.readTimeout = readTimeoutMs
        connection.useCaches = false
        connection.setRequestProperty("X-KY-JARVIS-Intent", "ui-v1")
        if (accessToken != null) connection.setRequestProperty("Authorization", "Bearer $accessToken")
        if (body != null) {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", contentType)
        }
        headers.forEach { (name, value) -> connection.setRequestProperty(name, value) }
        return try {
            if (body != null) {
                connection.outputStream.use { it.write(body) }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            HttpResponse(code, stream?.bufferedReader()?.use { it.readText() }.orEmpty())
        } finally {
            connection.disconnect()
        }
    }

    private fun parseReply(response: JSONObject): MobileReply {
        val steps = response.optJSONArray("steps") ?: JSONArray()
        return MobileReply(
            summary = response.getString("summary"),
            steps =
                buildList {
                    for (index in 0 until steps.length()) add(steps.getString(index))
                },
            requiresApproval = response.optBoolean("requires_approval", false),
            route = response.optString("route", "project"),
        )
    }

    private fun stringList(values: JSONArray?): List<String> =
        buildList {
            val source = values ?: JSONArray()
            for (index in 0 until source.length()) add(source.getString(index))
        }

    private data class HttpResponse(
        val code: Int,
        val text: String,
    )

    companion object {
        private const val MAX_VOICE_BYTES = 16_000 * 2 * 30
    }
}
