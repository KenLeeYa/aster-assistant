package tw.ky.jarvis.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class TokenVault(
    context: Context,
) {
    private val preferences = context.getSharedPreferences("ky_jarvis_token_vault", Context.MODE_PRIVATE)

    fun put(
        name: String,
        value: String,
    ) {
        require(name in ALLOWED_NAMES) { "unsupported token slot" }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val ciphertext = cipher.doFinal(value.encodeToByteArray())
        preferences.edit {
            putString("$name.iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            putString("$name.ct", Base64.encodeToString(ciphertext, Base64.NO_WRAP))
        }
    }

    fun get(name: String): String? {
        require(name in ALLOWED_NAMES) { "unsupported token slot" }
        val iv = preferences.getString("$name.iv", null) ?: return null
        val ciphertext = preferences.getString("$name.ct", null) ?: return null
        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                key(),
                GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
            )
            cipher.doFinal(Base64.decode(ciphertext, Base64.NO_WRAP)).decodeToString()
        }.getOrNull()
    }

    fun clear() {
        preferences.edit { clear() }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec
                .Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }

    companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val KEY_ALIAS = "ky-jarvis-token-vault-aes-v1"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private val ALLOWED_NAMES = setOf("device_id", "family_id", "access_token", "refresh_token")
    }
}
