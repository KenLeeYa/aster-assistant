package tw.ky.jarvis.ui

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import tw.ky.jarvis.network.MobileAgendaSummary
import tw.ky.jarvis.network.MobileApprovalRequest
import tw.ky.jarvis.network.MobileCommand
import tw.ky.jarvis.network.MobileProjectSummary
import tw.ky.jarvis.network.MobileReply
import tw.ky.jarvis.network.PairingPayload
import java.util.UUID

private val tabs = listOf("首頁", "對話", "行程", "專案", "核准", "設定")

@Suppress("LongParameterList")
@Composable
fun JarvisApp(
    coreBaseUrl: String,
    onRefreshWorker: ((Boolean) -> Unit) -> Unit,
    onPushToTalk: (Boolean) -> Unit,
    assistantStatus: String,
    onOpenAssistantSettings: () -> Unit,
    pairingPayload: PairingPayload?,
    pairingStatus: String,
    onCompletePairing: (PairingPayload) -> Unit,
    onClaimPairing: (PairingPayload) -> Unit,
    mobileStatus: String = "等待安全 channel 同步",
    latestCommand: MobileCommand? = null,
    conversationStatus: String = "可傳送文字到本機模型",
    conversationReply: MobileReply? = null,
    onSyncMobile: () -> Unit = {},
    onCommandDisplayed: (UUID) -> Unit = {},
    onSendMessage: (String) -> Unit = {},
    projects: List<MobileProjectSummary> = emptyList(),
    agenda: List<MobileAgendaSummary> = emptyList(),
    approvals: List<MobileApprovalRequest> = emptyList(),
    approvalStatus: String = "高風險動作必須以強式生物辨識簽章",
    onApprovalDecision: (MobileApprovalRequest, Boolean) -> Unit = { _, _ -> },
) {
    var tab by remember { mutableIntStateOf(0) }
    var workerOnline by remember { mutableStateOf(false) }
    LaunchedEffect(coreBaseUrl) {
        onRefreshWorker { workerOnline = it }
    }
    LaunchedEffect(latestCommand?.id) {
        latestCommand?.let { onCommandDisplayed(it.id) }
    }
    MaterialTheme {
        Scaffold(
            bottomBar = {
                NavigationBar {
                    tabs.forEachIndexed { index, label ->
                        NavigationBarItem(
                            selected = tab == index,
                            onClick = { tab = index },
                            icon = { Text(label.take(1)) },
                            label = { Text(label) },
                        )
                    }
                }
            },
        ) { padding ->
            Column(
                modifier =
                    Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .padding(16.dp)
                        .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("KY-JARVIS", style = MaterialTheme.typography.headlineMedium)
                StatusCard(workerOnline, coreBaseUrl)
                PairingCard(
                    pairingPayload,
                    pairingStatus,
                    onCompletePairing,
                    onClaimPairing,
                )
                when (tab) {
                    0 -> {
                        Home(
                            onRefreshWorker,
                            { workerOnline = it },
                            onPushToTalk,
                            mobileStatus,
                            latestCommand,
                            onSyncMobile,
                            conversationStatus,
                        )
                    }

                    1 -> {
                        Conversation(
                            conversationStatus,
                            conversationReply,
                            onSendMessage,
                        )
                    }

                    2 -> {
                        Agenda(agenda)
                    }

                    3 -> {
                        Projects(projects)
                    }

                    4 -> {
                        Approvals(approvals, approvalStatus, onApprovalDecision)
                    }

                    else -> {
                        Settings(assistantStatus, onOpenAssistantSettings)
                    }
                }
            }
        }
    }
}

@Composable
private fun PairingCard(
    payload: PairingPayload?,
    status: String,
    onComplete: (PairingPayload) -> Unit,
    onClaim: (PairingPayload) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("安全裝置配對", style = MaterialTheme.typography.titleMedium)
            Text(status)
            if (payload != null) {
                Text("比對碼：${payload.comparisonCode}")
                Text("伺服器指紋：${payload.serverFingerprint}")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { onComplete(payload) }) { Text("送交桌面確認") }
                    Button(onClick = { onClaim(payload) }) { Text("領取一次性 session") }
                }
            } else {
                Text("請由桌面產生 QR 配對連結；配對秘密不會寫入日誌。")
            }
        }
    }
}

@Composable
private fun StatusCard(
    online: Boolean,
    baseUrl: String,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(if (online) "Windows worker 已連線" else "Windows worker 離線")
            Text(
                if (baseUrl.isBlank()) "Release 尚未設定私人端點" else "Local-only 開發端點已設定",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun Home(
    onRefreshWorker: ((Boolean) -> Unit) -> Unit,
    onWorkerResult: (Boolean) -> Unit,
    onPushToTalk: (Boolean) -> Unit,
    mobileStatus: String,
    latestCommand: MobileCommand?,
    onSyncMobile: () -> Unit,
    voiceStatus: String,
) {
    val pushToTalkInteractions = remember { MutableInteractionSource() }
    LaunchedEffect(pushToTalkInteractions, onPushToTalk) {
        pushToTalkInteractions.interactions.collect { interaction ->
            when (interaction) {
                is PressInteraction.Press -> onPushToTalk(true)

                is PressInteraction.Release,
                is PressInteraction.Cancel,
                -> onPushToTalk(false)
            }
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = { onRefreshWorker(onWorkerResult) }) { Text("重新檢查") }
        Button(onClick = onSyncMobile) { Text("同步手機") }
        Button(
            onClick = { },
            interactionSource = pushToTalkInteractions,
        ) { Text("按住說話") }
    }
    Text(mobileStatus)
    Text(voiceStatus)
    latestCommand?.let { command ->
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text("Windows 訊息", style = MaterialTheme.typography.labelMedium)
                Text(command.title, style = MaterialTheme.typography.titleMedium)
                Text(command.body)
                Text("已安全接收並回傳顯示回執", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
    Text("麥克風只在可見按壓期間啟用；放開後送至 Windows 本機轉錄，原始音訊不保存。")
}

@Composable
private fun Conversation(
    status: String,
    reply: MobileReply?,
    onSendMessage: (String) -> Unit,
) {
    var message by remember { mutableStateOf("") }
    OutlinedTextField(
        value = message,
        onValueChange = { message = it },
        modifier = Modifier.fillMaxWidth(),
        label = { Text("傳給 Windows 本機模型") },
        minLines = 3,
    )
    Button(
        enabled = message.isNotBlank() && !status.contains("處理中"),
        onClick = {
            onSendMessage(message)
            message = ""
        },
    ) { Text("送出到本機") }
    Text(status)
    reply?.let { result ->
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text("JARVIS 本機回覆", style = MaterialTheme.typography.titleMedium)
                Text(result.summary)
                result.steps.forEachIndexed { index, step -> Text("${index + 1}. $step") }
                if (result.requiresApproval) {
                    Text("此計畫需要另行核准", color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

@Composable
private fun Settings(
    status: String,
    onOpenAssistantSettings: () -> Unit,
) {
    Text("Android 會在系統頁面列出可用助理；由你親自選擇或維持原設定。")
    Text(status)
    Spacer(Modifier.height(4.dp))
    Button(onClick = onOpenAssistantSettings) { Text("開啟預設助理設定") }
}

@Composable
private fun Agenda(items: List<MobileAgendaSummary>) {
    Text("行程預覽", style = MaterialTheme.typography.titleLarge)
    if (items.isEmpty()) Text("目前沒有待審閱的排程；手機不會直接寫入外部日曆。")
    items.forEach { item ->
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(item.timezone, style = MaterialTheme.typography.titleMedium)
                item.blocks.forEach { Text(it) }
                item.conflicts.forEach { Text("衝突：$it", color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

@Composable
private fun Projects(items: List<MobileProjectSummary>) {
    Text("專案", style = MaterialTheme.typography.titleLarge)
    if (items.isEmpty()) Text("目前沒有本機專案預覽。")
    items.forEach { item ->
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(item.title, style = MaterialTheme.typography.titleMedium)
                Text("工作項目：${item.workItemCount}")
                item.risks.forEach { Text("風險：$it", color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

@Composable
private fun Approvals(
    items: List<MobileApprovalRequest>,
    status: String,
    onDecision: (MobileApprovalRequest, Boolean) -> Unit,
) {
    Text("待核准動作", style = MaterialTheme.typography.titleLarge)
    Text(status)
    if (items.isEmpty()) Text("目前沒有待核准動作。")
    items.forEach { item ->
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(item.title, style = MaterialTheme.typography.titleMedium)
                Text(item.reason)
                Text("目標：${item.target}")
                Text("風險：${item.riskLevel}")
                Text("預覽：${item.preview}")
                Text("權限：${item.permissions.joinToString().ifBlank { "無" }}")
                item.sideEffects.forEach { Text("副作用：$it") }
                Text("回復方式：${item.rollbackMethod}")
                Text("Action hash：${item.actionHash.take(16)}…")
                Text("到期：${item.expiresAt}", style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { onDecision(item, false) }) { Text("拒絕並簽章") }
                    Button(onClick = { onDecision(item, true) }) { Text("生物辨識核准") }
                }
            }
        }
    }
}
