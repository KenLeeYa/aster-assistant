package tw.ky.jarvis

import android.app.role.RoleManager
import android.content.Intent
import android.provider.Settings
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.xmlpull.v1.XmlPullParser

@RunWith(AndroidJUnit4::class)
class AssistantRoleInstrumentedTest {
    @Test
    fun assistantRoleMetadataAndSettingsRouteAreAvailable() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val manager = context.getSystemService(RoleManager::class.java)

        assertTrue("Android reports ROLE_ASSISTANT unavailable", manager.isRoleAvailable(RoleManager.ROLE_ASSISTANT))
        assertNotNull(
            "No Android activity can open the default assistant settings",
            Intent(Settings.ACTION_VOICE_INPUT_SETTINGS).resolveActivity(context.packageManager),
        )

        val parser = context.resources.getXml(R.xml.voice_interaction_service)
        try {
            while (parser.eventType != XmlPullParser.START_TAG &&
                parser.eventType != XmlPullParser.END_DOCUMENT
            ) {
                parser.next()
            }
            assertEquals("voice-interaction-service", parser.name)
            assertNotNull(
                "VoiceInteractionService metadata must declare recognitionService",
                parser.getAttributeValue(
                    "http://schemas.android.com/apk/res/android",
                    "recognitionService",
                ),
            )
        } finally {
            parser.close()
        }
    }
}
