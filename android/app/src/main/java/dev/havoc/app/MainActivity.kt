package dev.havoc.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient

/**
 * The phone app is the same HUD the PC shows (so it's the same brain and the same conversation),
 * plus native extras: the "Hey Havoc" service, photo picking and mic permission.
 */
class MainActivity : Activity() {
    private lateinit var prefs: Prefs
    private lateinit var web: WebView
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var pendingWebPermission: PermissionRequest? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        if (!prefs.configured) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            if (prefs.session.isNotBlank()) setCookie(prefs.serverUrl, "${Prefs.COOKIE}=${prefs.session}; Path=/")
        }
        web = WebView(this).apply {
            setBackgroundColor(0xFF0C0D10.toInt())
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            addJavascriptInterface(NativeBridge(), "HavocNative")
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                    val url = req.url.toString()
                    if (url.startsWith(prefs.serverUrl)) return false
                    startActivity(Intent(Intent.ACTION_VIEW, req.url)) // outside links open in the browser
                    return true
                }
                override fun onPageFinished(view: WebView, url: String) {
                    CookieManager.getInstance().flush()
                    // Keep the native copy of the session fresh for the wake-word service.
                    CookieManager.getInstance().getCookie(prefs.serverUrl)?.split(";")
                        ?.map { it.trim() }?.firstOrNull { it.startsWith("${Prefs.COOKIE}=") }
                        ?.let { prefs.session = it.substringAfter("=") }
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onPermissionRequest(request: PermissionRequest) {
                    runOnUiThread {
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE !in request.resources) return@runOnUiThread request.deny()
                        if (hasMic()) request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
                        else {
                            pendingWebPermission = request
                            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_WEB_MIC)
                        }
                    }
                }
                override fun onShowFileChooser(view: WebView, cb: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                    fileCallback?.onReceiveValue(null)
                    fileCallback = cb
                    return runCatching { startActivityForResult(params.createIntent(), REQ_FILES); true }
                        .getOrElse { fileCallback = null; false }
                }
            }
        }
        setContentView(web)
        web.loadUrl(prefs.serverUrl + "/")
        if (prefs.wakeEnabled) WakeWordService.start(this)
    }

    private fun hasMic() = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun ensureWakePermissions(): Boolean {
        val needed = buildList {
            if (!hasMic()) add(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (needed.isEmpty()) return true
        requestPermissions(needed.toTypedArray(), REQ_WAKE)
        return false
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        when (requestCode) {
            REQ_WEB_MIC -> pendingWebPermission?.let {
                if (hasMic()) it.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE)) else it.deny()
                pendingWebPermission = null
            }
            REQ_WAKE -> if (hasMic()) { prefs.wakeEnabled = true; WakeWordService.start(this) }
        }
    }

    @Deprecated("Activity result API would need androidx; this app stays dependency-free.")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQ_FILES) {
            fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            fileCallback = null
        } else super.onActivityResult(requestCode, resultCode, data)
    }

    @Deprecated("Back handling via OnBackPressedDispatcher would need androidx.")
    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    /** Exposed to the HUD as window.HavocNative (see ui/src/lib/api.ts). */
    inner class NativeBridge {
        @JavascriptInterface fun appVersion(): String = BuildConfigShim.VERSION
        @JavascriptInterface fun isWakeEnabled(): Boolean = prefs.wakeEnabled
        @JavascriptInterface fun openSettings() = runOnUiThread { startActivity(Intent(this@MainActivity, SetupActivity::class.java)) }
        @JavascriptInterface fun setWakeEnabled(on: Boolean) = runOnUiThread {
            if (!on) {
                prefs.wakeEnabled = false
                WakeWordService.stop(this@MainActivity)
            } else if (ensureWakePermissions()) {
                prefs.wakeEnabled = true
                WakeWordService.start(this@MainActivity)
            }
        }
    }

    companion object {
        private const val REQ_FILES = 11
        private const val REQ_WEB_MIC = 12
        private const val REQ_WAKE = 13
    }
}

/** Version string without enabling BuildConfig generation. */
object BuildConfigShim { const val VERSION = "1.1.0" }
