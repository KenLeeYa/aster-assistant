package tw.ky.jarvis

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import tw.ky.jarvis.ui.JarvisApp

class PushToTalkUiTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun visiblePressEmitsStartThenStop() {
        val events = mutableListOf<Boolean>()
        composeRule.setContent {
            JarvisApp(
                coreBaseUrl = "http://127.0.0.1:8765",
                onRefreshWorker = { callback -> callback(false) },
                onPushToTalk = { active -> events += active },
                assistantStatus = "目前預設助理仍是其他應用程式",
                onOpenAssistantSettings = {},
                pairingPayload = null,
                pairingStatus = "尚未收到配對連結",
                onCompletePairing = {},
                onClaimPairing = {},
            )
        }

        composeRule.onNodeWithText("按住說話").performTouchInput {
            down(center)
            advanceEventTime(250)
            up()
        }

        composeRule.runOnIdle {
            assertEquals(listOf(true, false), events)
        }
    }
}
