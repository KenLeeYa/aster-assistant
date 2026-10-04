package tw.ky.jarvis

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import tw.ky.jarvis.network.MobileCommand
import tw.ky.jarvis.ui.JarvisApp
import java.time.Instant
import java.util.UUID

class BidirectionalUiTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun desktopCommandIsVisibleBeforeDisplayReceipt() {
        val commandId = UUID.fromString("11111111-1111-1111-1111-111111111111")
        val acknowledged = mutableListOf<UUID>()
        composeRule.setContent {
            JarvisApp(
                coreBaseUrl = "http://127.0.0.1:8765",
                onRefreshWorker = { callback -> callback(true) },
                onPushToTalk = {},
                assistantStatus = "KY-JARVIS 已是目前的預設助理",
                onOpenAssistantSettings = {},
                pairingPayload = null,
                pairingStatus = "安全配對完成",
                onCompletePairing = {},
                onClaimPairing = {},
                mobileStatus = "已從 Windows 收到 1 筆訊息",
                latestCommand =
                    MobileCommand(
                        id = commandId,
                        title = "桌面 QA",
                        body = "手機可見後才回傳顯示回執",
                        state = "delivered",
                        createdAt = Instant.parse("2026-09-01T00:00:00Z"),
                    ),
                onCommandDisplayed = { acknowledged += it },
            )
        }

        composeRule.onNodeWithText("桌面 QA").assertIsDisplayed()
        composeRule.onNodeWithText("手機可見後才回傳顯示回執").assertIsDisplayed()
        composeRule.runOnIdle { assertEquals(listOf(commandId), acknowledged) }
    }

    @Test
    fun workerStatusRefreshesWhenScreenStarts() {
        var refreshCount = 0
        composeRule.setContent {
            JarvisApp(
                coreBaseUrl = "http://127.0.0.1:8765",
                onRefreshWorker = { callback ->
                    refreshCount += 1
                    callback(true)
                },
                onPushToTalk = {},
                assistantStatus = "KY-JARVIS 已是目前的預設助理",
                onOpenAssistantSettings = {},
                pairingPayload = null,
                pairingStatus = "安全配對完成",
                onCompletePairing = {},
                onClaimPairing = {},
            )
        }

        composeRule.onNodeWithText("Windows worker 已連線").assertIsDisplayed()
        composeRule.runOnIdle { assertEquals(1, refreshCount) }
    }

    @Test
    fun conversationSendsTextToLocalCore() {
        val messages = mutableListOf<String>()
        composeRule.setContent {
            JarvisApp(
                coreBaseUrl = "http://127.0.0.1:8765",
                onRefreshWorker = { callback -> callback(true) },
                onPushToTalk = {},
                assistantStatus = "KY-JARVIS 已是目前的預設助理",
                onOpenAssistantSettings = {},
                pairingPayload = null,
                pairingStatus = "安全配對完成",
                onCompletePairing = {},
                onClaimPairing = {},
                onSendMessage = { messages += it },
            )
        }

        composeRule.onNodeWithText("對話").performClick()
        composeRule.onNodeWithText("傳給 Windows 本機模型").performTextInput("雙向 QA")
        composeRule.onNodeWithText("送出到本機").performClick()

        composeRule.runOnIdle { assertEquals(listOf("雙向 QA"), messages) }
    }
}
