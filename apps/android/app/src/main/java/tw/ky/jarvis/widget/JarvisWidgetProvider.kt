package tw.ky.jarvis.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import tw.ky.jarvis.MainActivity
import tw.ky.jarvis.R

class JarvisWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(
        context: Context,
        manager: AppWidgetManager,
        ids: IntArray,
    ) {
        ids.forEach { id ->
            val open =
                PendingIntent.getActivity(
                    context,
                    id,
                    Intent(context, MainActivity::class.java),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                )
            val views =
                RemoteViews(context.packageName, R.layout.jarvis_widget).apply {
                    setOnClickPendingIntent(R.id.widget_status, open)
                }
            manager.updateAppWidget(id, views)
        }
    }
}
