package tw.ky.jarvis.security

import android.os.Build
import android.util.Base64
import androidx.biometric.BiometricPrompt
import androidx.fragment.app.FragmentActivity
import java.security.KeyStore
import java.security.Signature
import java.time.OffsetDateTime
import java.util.UUID

class ApprovalSigner(
    private val activity: FragmentActivity,
) {
    fun authenticateAndSign(
        request: ApprovalToSign,
        onSigned: (ByteArray) -> Unit,
        onError: (String) -> Unit,
    ) {
        val payload =
            Payloads.approval(
                request.approvalId,
                request.actionHash,
                request.nonce,
                request.decision,
                request.deviceId,
                request.timestampIso,
            )
        val signature = approvalSignature()
        val prompt =
            BiometricPrompt(
                activity,
                activity.mainExecutor,
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                        val signer = result.cryptoObject?.signature
                        if (signer == null) {
                            onError("missing biometric signer")
                            return
                        }
                        signer.update(payload)
                        onSigned(signer.sign())
                    }

                    override fun onAuthenticationError(
                        errorCode: Int,
                        errString: CharSequence,
                    ) {
                        onError(errString.toString())
                    }
                },
            )
        prompt.authenticate(
            BiometricPrompt.PromptInfo
                .Builder()
                .setTitle("核准高風險動作")
                .setSubtitle("確認不可變 action hash 與目標後再核准")
                .setAllowedAuthenticators(
                    androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG,
                ).setNegativeButtonText("取消")
                .build(),
            BiometricPrompt.CryptoObject(signature),
        )
    }

    private fun approvalSignature(): Signature {
        ApprovalSigningKey.ensure()
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return Signature.getInstance("SHA256withECDSA").apply {
            initSign(store.getKey(ApprovalSigningKey.ALIAS, null) as java.security.PrivateKey)
        }
    }

    companion object {
        fun publicKeyPem(): String = ApprovalSigningKey.publicKeyPem()
    }
}

data class ApprovalToSign(
    val approvalId: UUID,
    val actionHash: String,
    val nonce: String,
    val decision: String,
    val deviceId: UUID,
    val timestampIso: String,
) {
    init {
        require(actionHash.matches(Regex("[0-9a-f]{64}")))
        require(decision in setOf("approve", "deny"))
        OffsetDateTime.parse(timestampIso)
    }
}

private object ApprovalSigningKey {
    const val ALIAS = "ky-jarvis-biometric-approval-p256-v1"

    fun ensure() {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (store.containsAlias(ALIAS)) return
        val generator =
            java.security.KeyPairGenerator.getInstance(
                android.security.keystore.KeyProperties.KEY_ALGORITHM_EC,
                "AndroidKeyStore",
            )
        val builder =
            android.security.keystore.KeyGenParameterSpec
                .Builder(
                    ALIAS,
                    android.security.keystore.KeyProperties.PURPOSE_SIGN,
                ).setAlgorithmParameterSpec(java.security.spec.ECGenParameterSpec("secp256r1"))
                .setDigests(android.security.keystore.KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .setInvalidatedByBiometricEnrollment(true)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            requireStrongBiometric(builder)
        } else {
            @Suppress("DEPRECATION")
            builder.setUserAuthenticationValidityDurationSeconds(-1)
        }
        generator.initialize(builder.build())
        generator.generateKeyPair()
    }

    fun publicKeyPem(): String {
        ensure()
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val encoded =
            Base64.encodeToString(
                store.getCertificate(ALIAS).publicKey.encoded,
                Base64.NO_WRAP,
            )
        return encoded.chunked(64).joinToString(
            separator = "\n",
            prefix = "-----BEGIN PUBLIC KEY-----\n",
            postfix = "\n-----END PUBLIC KEY-----\n",
        )
    }

    @androidx.annotation.RequiresApi(Build.VERSION_CODES.R)
    private fun requireStrongBiometric(builder: android.security.keystore.KeyGenParameterSpec.Builder) {
        builder.setUserAuthenticationParameters(
            0,
            android.security.keystore.KeyProperties.AUTH_BIOMETRIC_STRONG,
        )
    }
}
