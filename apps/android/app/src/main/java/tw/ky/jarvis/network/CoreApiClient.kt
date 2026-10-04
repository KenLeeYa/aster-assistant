package tw.ky.jarvis.network

import java.net.HttpURLConnection
import java.net.URL

class CoreApiClient(
    private val baseUrl: String,
) {
    fun isWorkerReady(): Boolean {
        if (baseUrl.isBlank()) return false
        return runCatching {
            val connection = URL("${baseUrl.trimEnd('/')}/health").openConnection() as HttpURLConnection
            connection.requestMethod = "GET"
            connection.connectTimeout = 2_000
            connection.readTimeout = 2_000
            connection.useCaches = false
            try {
                connection.responseCode == HttpURLConnection.HTTP_OK &&
                    connection.inputStream
                        .bufferedReader()
                        .use { it.readText() }
                        .contains("\"status\":\"ok\"")
            } finally {
                connection.disconnect()
            }
        }.getOrDefault(false)
    }
}
