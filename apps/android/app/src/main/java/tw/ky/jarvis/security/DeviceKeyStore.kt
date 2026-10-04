package tw.ky.jarvis.security

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.UUID

class DeviceKeyStore(
    private val alias: String = DEVICE_KEY_ALIAS,
) {
    fun publicKeyPem(): String {
        ensureKey()
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val encoded =
            Base64.encodeToString(
                keyStore.getCertificate(alias).publicKey.encoded,
                Base64.NO_WRAP,
            )
        return encoded.chunked(64).joinToString(
            separator = "\n",
            prefix = "-----BEGIN PUBLIC KEY-----\n",
            postfix = "\n-----END PUBLIC KEY-----\n",
        )
    }

    fun pairingProof(
        sessionId: UUID,
        oneTimeSecret: String,
    ): String = Base64.encodeToString(sign(Payloads.pairing(sessionId, oneTimeSecret)), Base64.NO_WRAP)

    fun tokenClaimProof(
        sessionId: UUID,
        oneTimeSecret: String,
    ): String = Base64.encodeToString(sign(Payloads.tokenClaim(sessionId, oneTimeSecret)), Base64.NO_WRAP)

    fun sign(payload: ByteArray): ByteArray {
        ensureKey()
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val signature = Signature.getInstance("SHA256withECDSA")
        signature.initSign(keyStore.getKey(alias, null) as java.security.PrivateKey)
        signature.update(payload)
        return signature.sign()
    }

    private fun ensureKey() {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        if (keyStore.containsAlias(alias)) return
        val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE)
        generator.initialize(
            KeyGenParameterSpec
                .Builder(
                    alias,
                    KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
                ).setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(false)
                .build(),
        )
        generator.generateKeyPair()
    }

    companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val DEVICE_KEY_ALIAS = "ky-jarvis-device-p256-v1"
    }
}

object Payloads {
    fun pairing(
        sessionId: UUID,
        oneTimeSecret: String,
    ): ByteArray = "ky-jarvis-pairing-v1:$sessionId:$oneTimeSecret".encodeToByteArray()

    fun tokenClaim(
        sessionId: UUID,
        oneTimeSecret: String,
    ): ByteArray = "ky-jarvis-token-claim-v1:$sessionId:$oneTimeSecret".encodeToByteArray()

    fun approval(
        approvalId: UUID,
        actionHash: String,
        nonce: String,
        decision: String,
        deviceId: UUID,
        timestampIso: String,
    ): ByteArray =
        "ky-jarvis-approval-v1:$approvalId:$actionHash:$nonce:$decision:$deviceId:$timestampIso"
            .encodeToByteArray()
}
