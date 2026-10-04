package tw.ky.jarvis.network

import android.os.Build
import org.json.JSONObject
import tw.ky.jarvis.security.ApprovalSigner
import tw.ky.jarvis.security.DeviceKeyStore
import tw.ky.jarvis.security.TokenVault
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLDecoder
import java.time.Instant
import java.util.UUID

data class PairingPayload(
    val sessionId: UUID,
    val oneTimeSecret: String,
    val comparisonCode: String,
    val serverFingerprint: String,
    val expiresAt: Instant,
) {
    init {
        require(oneTimeSecret.length >= 32)
        require(comparisonCode.matches(Regex("\\d{6}")))
        require(serverFingerprint.length >= 8)
    }

    fun requireUsable(now: Instant = Instant.now()) {
        require(now.isBefore(expiresAt)) { "配對碼已過期" }
    }

    companion object {
        fun fromUri(value: String): PairingPayload {
            val uri = URI(value)
            require(uri.scheme == "kyjarvis" && uri.host == "pair") { "不是 KY-JARVIS 配對連結" }
            val parameters =
                uri.rawQuery
                    .orEmpty()
                    .split('&')
                    .filter { it.isNotBlank() }
                    .associate { item ->
                        val pair = item.split('=', limit = 2)

                        @Suppress("DEPRECATION")
                        val name = URLDecoder.decode(pair[0], "UTF-8")

                        @Suppress("DEPRECATION")
                        val valuePart = URLDecoder.decode(pair.getOrElse(1) { "" }, "UTF-8")
                        name to valuePart
                    }

            fun required(name: String): String = requireNotNull(parameters[name]) { "配對連結缺少 $name" }
            return PairingPayload(
                sessionId = UUID.fromString(required("session_id")),
                oneTimeSecret = required("secret"),
                comparisonCode = required("comparison_code"),
                serverFingerprint = required("fingerprint"),
                expiresAt = Instant.parse(required("expires_at")),
            ).also { it.requireUsable() }
        }
    }
}

data class PendingDevice(
    val deviceId: UUID,
    val comparisonCode: String,
)

class PairingClient(
    private val baseUrl: String,
    private val keys: DeviceKeyStore,
    private val vault: TokenVault,
) {
    fun complete(payload: PairingPayload): PendingDevice {
        payload.requireUsable()
        val approvalPublicKey = runCatching { ApprovalSigner.publicKeyPem() }.getOrNull()
        val body =
            JSONObject()
                .put("session_id", payload.sessionId.toString())
                .put("one_time_secret", payload.oneTimeSecret)
                .put("public_key_pem", keys.publicKeyPem())
                .put("proof_signature_b64", keys.pairingProof(payload.sessionId, payload.oneTimeSecret))
                .put("user_id", "local-user")
                .put("display_name", "${Build.MANUFACTURER} ${Build.MODEL}")
                .put("app_version", "0.1.0")
                .put("os_version", "Android ${Build.VERSION.RELEASE}")
                .put(
                    "capabilities",
                    org.json.JSONArray(
                        buildList {
                            add("ptt")
                            if (approvalPublicKey != null) add("biometric-approval")
                        },
                    ),
                )
        if (approvalPublicKey != null) {
            body.put("approval_public_key_pem", approvalPublicKey)
        }
        val response = post("/api/v1/device-pairings/complete", body)
        return PendingDevice(UUID.fromString(response.getString("id")), payload.comparisonCode)
    }

    fun claim(payload: PairingPayload) {
        val body =
            JSONObject()
                .put("one_time_secret", payload.oneTimeSecret)
                .put(
                    "proof_signature_b64",
                    keys.tokenClaimProof(payload.sessionId, payload.oneTimeSecret),
                )
        val response = post("/api/v1/device-pairings/${payload.sessionId}/claim", body)
        vault.put("device_id", response.getString("device_id"))
        vault.put("family_id", response.getString("family_id"))
        vault.put("access_token", response.getString("access_token"))
        vault.put("refresh_token", response.getString("refresh_token"))
    }

    private fun post(
        path: String,
        body: JSONObject,
    ): JSONObject {
        require(baseUrl.isNotBlank()) { "Core API 端點尚未設定" }
        val connection = URL("${baseUrl.trimEnd('/')}$path").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 5_000
        connection.readTimeout = 5_000
        connection.doOutput = true
        connection.useCaches = false
        connection.setRequestProperty("Content-Type", "application/json")
        connection.setRequestProperty("X-KY-JARVIS-Intent", "ui-v1")
        return try {
            connection.outputStream.use { it.write(body.toString().encodeToByteArray()) }
            val stream =
                if (connection.responseCode in 200..299) {
                    connection.inputStream
                } else {
                    connection.errorStream
                }
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            check(connection.responseCode in 200..299) {
                JSONObject(text.ifBlank { "{}" }).optString("detail", "配對服務拒絕請求")
            }
            JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }
}
