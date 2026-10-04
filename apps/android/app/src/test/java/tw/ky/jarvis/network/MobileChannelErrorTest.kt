package tw.ky.jarvis.network

import org.junit.Assert.assertEquals
import org.junit.Test

class MobileChannelErrorTest {
    @Test
    fun unauthorizedResponseDoesNotExposeServerDetail() {
        val serverDetail = """{"detail":"UUID('00000000-0000-0000-0000-000000000000')"}"""

        assertEquals(
            "安全 session 已失效，請重新配對",
            mobileErrorDetail(401, serverDetail, "Core 拒絕手機請求"),
        )
    }
}
