package tw.ky.jarvis

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import tw.ky.jarvis.ui.JarvisApp

class AssistantSettingsUiTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun settingsShowsStatusAndOpensSystemPicker() {
        var openCount = 0
        composeRule.setContent {
            JarvisApp(
                coreBaseUrl = "http://127.0.0.1:8765",
                onRefreshWorker = { callback -> callback(false) },
                onPushToTalk = {},
                assistantStatus = "目前預設助理仍是其他應用程式",
                onOpenAssistantSettings = { openCount += 1 },
                pairingPayload = null,
                pairingStatus = "尚未收到配對連結",
                onCompletePairing = {},
                onClaimPairing = {},
            )
        }

        composeRule.onNodeWithText("設定").performClick()
        composeRule.onNodeWithText("目前預設助理仍是其他應用程式").assertIsDisplayed()
        composeRule.onNodeWithText("開啟預設助理設定").performClick()

        composeRule.runOnIdle {
            assertEquals(1, openCount)
        }
    }
}
