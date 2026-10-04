package tw.ky.jarvis

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import tw.ky.jarvis.network.MobileApprovalRequest
import tw.ky.jarvis.ui.JarvisApp
import java.util.UUID

class MobileApprovalUiTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun pendingApprovalShowsImmutableDetailsBeforeBiometricCallback() {
        val approval =
            MobileApprovalRequest(
                id = UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                title = "建立測試行程",
                reason = "驗證 mobile approval UI",
                target = "calendar:calendar.create.fake",
                riskLevel = "r3",
                preview = "{\"title\":\"Mobile approval contract\"}",
                permissions = listOf("calendar.write"),
                sideEffects = listOf("建立 fake event"),
                rollbackMethod = "刪除 fake event",
                actionHash = "b".repeat(64),
                nonce = "mobile-nonce",
                expiresAt = "2026-09-02T02:00:00+00:00",
            )
        val decisions = mutableListOf<Boolean>()
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
                approvals = listOf(approval),
                onApprovalDecision = { _, approved -> decisions += approved },
            )
        }

        composeRule.onNodeWithText("核准").performClick()
        composeRule.onNodeWithText("建立測試行程").assertIsDisplayed()
        composeRule.onNodeWithText("Action hash：${"b".repeat(16)}…").assertIsDisplayed()
        composeRule.onNodeWithText("生物辨識核准").performClick()

        composeRule.runOnIdle { assertEquals(listOf(true), decisions) }
    }
}
