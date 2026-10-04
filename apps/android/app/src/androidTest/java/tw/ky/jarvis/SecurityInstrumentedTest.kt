package tw.ky.jarvis

import android.content.Context
import android.content.pm.ApplicationInfo
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import tw.ky.jarvis.security.DeviceKeyStore
import tw.ky.jarvis.security.TokenVault
import java.security.KeyStore

@RunWith(AndroidJUnit4::class)
class SecurityInstrumentedTest {
    @Suppress("DEPRECATION")
    @Test
    fun backupIsDisabledAndDeviceKeyIsNonExported() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        assertEquals(0, context.applicationInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP)

        val alias = "ky-jarvis-instrumented-device-key"
        try {
            val pem = DeviceKeyStore(alias).publicKeyPem()
            assertTrue(pem.startsWith("-----BEGIN PUBLIC KEY-----"))
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            assertTrue(store.containsAlias(alias))
            assertFalse(store.getKey(alias, null).encoded?.isNotEmpty() == true)
        } finally {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            if (store.containsAlias(alias)) store.deleteEntry(alias)
        }
    }

    @Test
    fun tokenVaultDoesNotStorePlaintext() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val vault = TokenVault(context)
        val marker = "instrumented-token-marker"
        try {
            vault.put("access_token", marker)
            assertEquals(marker, vault.get("access_token"))
            val preferences =
                context.getSharedPreferences(
                    "ky_jarvis_token_vault",
                    Context.MODE_PRIVATE,
                )
            assertFalse(
                preferences.all.values
                    .joinToString()
                    .contains(marker),
            )
        } finally {
            vault.clear()
        }
    }
}
