package ai.niblit.mobile

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.*
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.net.URL
import java.util.concurrent.Executors
import javax.net.ssl.HttpsURLConnection

/** Android control frontend: Client Portal authentication; demo actions only. */
class MainActivity : Activity() {
    private val work = Executors.newSingleThreadExecutor()
    private var token: String? = null
    private var isAdmin = false
    private var proposalId: String? = null
    private var proposalHash: String? = null
    private var sessionId: String? = null
    private var busy = false
    private val history = mutableListOf<Pair<String, String>>()
    private val modelIds = mutableListOf("qwen2.5-coder-3b")
    private val markets = mutableListOf<String>()

    private val bg = Color.rgb(8, 18, 28)
    private val card = Color.rgb(19, 34, 46)
    private val inset = Color.rgb(30, 48, 60)
    private val cyan = Color.rgb(35, 222, 204)
    private val white = Color.rgb(242, 248, 255)
    private val muted = Color.rgb(160, 182, 194)
    private val violet = Color.rgb(173, 150, 250)

    private lateinit var banner: TextView
    private lateinit var homeStatus: TextView
    private lateinit var sessionStatus: TextView
    private lateinit var accountStatus: TextView
    private lateinit var hostInput: EditText
    private lateinit var usernameInput: EditText
    private lateinit var passwordInput: EditText
    private lateinit var confirmInput: EditText
    private lateinit var workspaceAck: CheckBox
    private lateinit var modelSpinner: Spinner
    private lateinit var messages: LinearLayout
    private lateinit var prompt: EditText
    private lateinit var send: Button
    private lateinit var marketSpinner: Spinner
    private lateinit var marketDetails: TextView
    private lateinit var advisoryText: TextView
    private lateinit var tradeStatus: TextView
    private lateinit var symbol: EditText
    private lateinit var volume: EditText
    private lateinit var minutes: EditText
    private lateinit var entries: EditText
    private lateinit var positions: EditText
    private lateinit var riskPercent: EditText
    private lateinit var riskCash: EditText
    private val tabs = mutableListOf<View>()
    private val nav = mutableListOf<Button>()

    private fun dp(px: Int) = (px * resources.displayMetrics.density + .5f).toInt()

    private fun rounded(color: Int = card, radius: Int = 17) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = dp(radius).toFloat()
    }

    private fun text(value: String, size: Int = 14, bold: Boolean = false,
                     color: Int = white): TextView = TextView(this).apply {
        this.text = value
        textSize = size.toFloat()
        setTextColor(color)
        setPadding(0, dp(5), 0, dp(5))
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun field(hint: String, initial: String = "", number: Boolean = false) = EditText(this).apply {
        this.hint = hint
        setText(initial)
        textSize = 15f
        setTextColor(white)
        setHintTextColor(muted)
        background = rounded(inset, 13)
        setPadding(dp(14), dp(11), dp(14), dp(11))
        if (number) inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
    }

    private fun button(title: String, secondary: Boolean = false) = Button(this).apply {
        text = title
        isAllCaps = false
        textSize = 13f
        setTextColor(if (secondary) white else bg)
        background = rounded(if (secondary) inset else cyan, 13)
        minHeight = dp(46)
        minimumHeight = dp(46)
        elevation = 0f
    }

    private fun column() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
    }

    private fun page() = column().apply {
        setPadding(dp(18), dp(12), dp(18), dp(28))
    }

    private fun panel() = column().apply {
        background = rounded()
        setPadding(dp(16), dp(15), dp(16), dp(15))
    }

    private fun append(parent: LinearLayout, view: View, top: Int = 10) {
        parent.addView(view, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(top) })
    }

    private fun heading(parent: LinearLayout, name: String, caption: String) {
        append(parent, text(name, 23, true), 8)
        append(parent, text(caption, 13, false, muted), 0)
    }

    private fun scroll(child: LinearLayout) = ScrollView(this).apply {
        isFillViewport = true
        addView(child)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        val shell = column().apply { setBackgroundColor(bg) }
        setContentView(shell)

        val masthead = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(18), dp(10), dp(18), dp(10))
        }
        masthead.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_niblit_windows)
            scaleType = ImageView.ScaleType.FIT_CENTER
            background = rounded(inset)
        }, LinearLayout.LayoutParams(dp(48), dp(48)))
        masthead.addView(column().apply {
            setPadding(dp(12), 0, 0, 0)
            addView(text("Niblit", 22, true))
            addView(text("AI OS  •  Market Intelligence", 11, false, cyan))
        }, LinearLayout.LayoutParams(0, -2, 1f))
        val account = button("Account", true)
        masthead.addView(account, LinearLayout.LayoutParams(dp(90), dp(44)))
        account.setOnClickListener { showTab(3) }
        shell.addView(masthead)

        banner = text("●  Private gateway · Sign in to connect", 12, true, cyan).apply {
            background = rounded(card, 11)
            setPadding(dp(14), dp(11), dp(14), dp(11))
        }
        shell.addView(banner, LinearLayout.LayoutParams(-1, -2).apply {
            leftMargin = dp(18); rightMargin = dp(18); bottomMargin = dp(6)
        })

        val stack = FrameLayout(this)
        shell.addView(stack, LinearLayout.LayoutParams(-1, 0, 1f))
        for (page in listOf(buildHome(), buildChat(), buildMarkets(), buildAccount())) {
            val view = scroll(page)
            tabs.add(view)
            stack.addView(view)
        }

        val navigation = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(8), dp(8), dp(8), dp(9))
            background = rounded(card, 0)
        }
        for ((index, label) in listOf("⌂ Home", "✦ AI Chat", "◈ Market", "♙ Account").withIndex()) {
            val tab = button(label, true).apply { textSize = 11f }
            nav.add(tab)
            navigation.addView(tab, LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                leftMargin = dp(2); rightMargin = dp(2)
            })
            tab.setOnClickListener { showTab(index) }
        }
        shell.addView(navigation)
        showTab(0)
    }

    private fun showTab(index: Int) {
        for (i in tabs.indices) {
            tabs[i].visibility = if (i == index) View.VISIBLE else View.GONE
            nav[i].background = rounded(if (i == index) cyan else inset, 12)
            nav[i].setTextColor(if (i == index) bg else muted)
        }
    }

    private fun buildHome() = page().apply {
        val hero = panel().apply {
            background = rounded(Color.rgb(16, 56, 65), 21)
            addView(text("NIBLIT  •  R14", 11, true, cyan))
            addView(text("Welcome to Niblit", 25, true))
            addView(text("Your AI, connected devices, market intelligence and desktop control centre.", 13, false, muted))
        }
        append(this, hero)
        homeStatus = text("Sign in to see your desktop's live status.", 15, true, cyan)
        append(this, panel().apply {
            addView(text("R14 CONNECTION", 11, true, muted))
            addView(homeStatus)
        })
        append(this, panel().apply {
            addView(text("✦  AI CHAT & MEMORY", 15, true, cyan))
            addView(text("Choose your local LLM and continue conversations securely.", 13, false, muted))
            addView(button("Open AI Chat").apply { setOnClickListener { showTab(1) } })
        })
        append(this, panel().apply {
            addView(text("◈  MARKET DESK & MT5", 15, true, cyan))
            addView(text("Monitor instruments, review demo trade settings and manage session activation.", 13, false, muted))
            addView(button("Open Market Desk").apply { setOnClickListener { showTab(2) } })
        })
        append(this, button("↻ Refresh system & session status", true).apply { setOnClickListener { refreshHome() } })
    }

    private fun buildChat() = page().apply {
        heading(this, "Niblit AI Chat", "Local inference · Memory-aware conversations")
        append(this, panel().apply {
            addView(text("MODEL", 11, true, muted))
            modelSpinner = Spinner(this@MainActivity).apply {
                adapter = ArrayAdapter(this@MainActivity,
                    android.R.layout.simple_spinner_dropdown_item, modelIds)
                background = rounded(inset)
            }
            addView(modelSpinner)
            addView(button("↻ Refresh local models", true).apply {
                setOnClickListener { loadModels() }
            })
        })
        messages = column()
        append(this, messages, 12)
        bubble("assistant", "Hello. I'm Niblit. Sign in to your Client Portal account to use my local models and market understanding.")
        append(this, panel().apply {
            prompt = field("Message Niblit…").apply {
                minLines = 2; maxLines = 5
                setSingleLine(false)
            }
            addView(prompt)
            send = button("➤ Send to Niblit")
            addView(send)
            send.setOnClickListener { sendChat() }
        }, 14)
        append(this, text("AI market interpretation may be inaccurate; it cannot authorize a broker trade.", 11, false, muted))
    }

    private fun bubble(role: String, message: String) {
        val user = role == "user"
        val body = panel().apply {
            background = rounded(if (user) Color.rgb(26, 74, 83) else card)
            addView(text(if (user) "YOU" else "✦ NIBLIT", 11, true, if (user) cyan else violet))
            addView(text(message, 14))
        }
        append(messages, body, 7)
    }

    private fun buildMarkets() = page().apply {
        heading(this, "Market Desk", "R14 strategies, demo controls and exit cognition")
        append(this, panel().apply {
            background = rounded(Color.rgb(16, 56, 65), 21)
            addView(text("◈  MT5 DEMO", 12, true, cyan))
            addView(text("Edit, review, propose and activate bounded autonomous demo sessions.", 13, false, muted))
        })
        sessionStatus = text("No session status loaded.", 14, true, cyan)
        append(this, panel().apply {
            addView(text("TRADING SESSION", 11, true, muted))
            addView(sessionStatus)
            addView(button("↻ Refresh sessions", true).apply {
                setOnClickListener { refreshSessions() }
            })
        })
        marketSpinner = Spinner(this@MainActivity).apply {
            adapter = ArrayAdapter(this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item, markets)
            background = rounded(inset)
        }
        marketDetails = text("No observations loaded.", 13, false, muted)
        append(this, panel().apply {
            addView(text("MARKET OBSERVATIONS", 11, true, cyan))
            addView(marketSpinner)
            addView(marketDetails)
            addView(button("↻ Load markets", true).apply { setOnClickListener { refreshMarkets() } })
        })
        heading(this, "Auto-trading configuration", "All values are verified by R14 and your MT5 demo broker.")
        val controls = panel()
        fun numeric(label: String, initial: String): EditText {
            controls.addView(text(label, 12, true, muted))
            val input = field(label, initial, true)
            append(controls, input, 2)
            return input
        }
        controls.addView(text("Broker symbol", 12, true, muted))
        symbol = field("ETHUSDm", "ETHUSDm")
        append(controls, symbol, 2)
        volume = numeric("Volume (lots)", "0.10")
        minutes = numeric("Session time (minutes)", "60")
        entries = numeric("Maximum entries", "3")
        positions = numeric("Maximum simultaneous positions", "1")
        riskPercent = numeric("Maximum risk per trade (%)", "0.25")
        riskCash = numeric("Maximum cash risk (account currency)", "25")
        append(this, controls)
        tradeStatus = text("Not reviewed. No session changes sent.", 13, false, muted)
        append(this, panel().apply {
            addView(text("REVIEWED EXECUTION SCOPE", 11, true, cyan))
            addView(tradeStatus)
        })
        append(this, button("1 · Review with R14 + MT5").apply {
            setOnClickListener { tradeAction("readiness") }
        })
        append(this, button("2 · Propose reviewed session", true).apply {
            setOnClickListener { tradeAction("propose") }
        })
        append(this, button("3 · Activate DEMO session").apply {
            setOnClickListener { tradeAction("activate") }
        })
        append(this, button("Stop selected session", true).apply {
            setOnClickListener { tradeAction("stop") }
        })
        heading(this, "Exit Cognition", "Evidence-based advice; broker action remains separately authorized.")
        advisoryText = text("Select an observed instrument and request an AI explanation.", 13, false, muted)
        append(this, panel().apply {
            addView(advisoryText)
            addView(button("✦ Explain with AI", true).apply {
                setOnClickListener { explainMarket() }
            })
        })
    }

    private fun buildAccount() = page().apply {
        heading(this, "Client Portal", "Account, access, devices and administrator approval")
        accountStatus = text("● Not signed in", 15, true, cyan)
        append(this, panel().apply {
            addView(text("ACCOUNT STATUS", 11, true, muted))
            addView(accountStatus)
            addView(text("Approved users can chat and view market observations. Only administrators can activate demo trading.", 12, false, muted))
        })
        append(this, text("PRIVATE HTTPS GATEWAY", 12, true, cyan), 14)
        hostInput = field("https://your-private-niblit-gateway").apply {
            setText("https://niblit.tail9bfde8.ts.net")
        }
        append(this, hostInput)
        append(this, text("Niblit Core runs on your Windows PC. Connect through your private TLS/Tailscale address, not desktop localhost.", 12, false, muted))
        usernameInput = field("Username")
        passwordInput = field("Password").apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        confirmInput = field("Confirm password (sign-up only)").apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        append(this, usernameInput)
        append(this, passwordInput)
        append(this, confirmInput)
        workspaceAck = CheckBox(this@MainActivity).apply {
            text = "I understand approved members can see shared-workspace conversations."
            setTextColor(muted)
        }
        append(this, workspaceAck)
        append(this, button("Log in").apply { setOnClickListener { authenticate(false) } })
        append(this, button("Sign up · Request administrator approval", true).apply {
            setOnClickListener { authenticate(true) }
        })
        append(this, button("Log out", true).apply { setOnClickListener { signOut() } })
        append(this, text("Account approval is issued by your existing Client Portal. This app never stores broker credentials.", 12, false, muted))
    }

    private fun base(): String {
        val raw = hostInput.text.toString().trim().trimEnd('/')
        val uri = URI(raw)
        require(uri.scheme == "https" && !uri.host.isNullOrBlank()
            && uri.host != "127.0.0.1" && uri.host != "localhost"
            && uri.rawUserInfo == null && uri.path.isNullOrEmpty()
            && uri.query == null && uri.fragment == null) {
            "Enter the private Niblit HTTPS gateway without any path."
        }
        return raw
    }

    private fun request(host: String, access: String?, path: String, body: JSONObject? = null): JSONObject {
        val connection = (URL(host + path).openConnection() as HttpsURLConnection).apply {
            connectTimeout = 12000
            readTimeout = if (path.endsWith("/chat")) 240000 else 25000
            instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json")
            if (!access.isNullOrEmpty()) setRequestProperty("Authorization", "Bearer " + access)
            if (body != null) {
                requestMethod = "POST"
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
        }
        return try {
            val code = connection.responseCode
            require(code in 200..299) { "Niblit gateway HTTP $code" }
            JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
        } finally { connection.disconnect() }
    }

    private fun task(message: String, action: () -> Unit) {
        banner.text = "◌ " + message
        work.execute {
            try { action() }
            catch (exc: Exception) {
                runOnUiThread {
                    banner.text = "● " + (exc.message ?: "Private gateway unavailable")
                    Toast.makeText(this, banner.text, Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun authenticate(signup: Boolean) {
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        val user = usernameInput.text.toString().trim()
        val password = passwordInput.text.toString()
        if (user.length !in 3..80 || password.length < 12) {
            banner.text = "Username 3–80 characters; password 12 characters minimum."
            return
        }
        if (signup && (confirmInput.text.toString() != password || !workspaceAck.isChecked)) {
            banner.text = "Confirm your password and acknowledge workspace visibility."
            return
        }
        val body = JSONObject().put("username", user).put("password", password)
        if (signup) body.put("shared_workspace_acknowledged", true)
        task(if (signup) "Requesting admin approval…" else "Signing in…") {
            val response = request(host, null,
                if (signup) "/mobile/signup" else "/mobile/login", body)
            val newToken = if (signup) null else response.getString("session_token")
            val profile = if (newToken == null) null else request(host, newToken, "/mobile/me")
            runOnUiThread {
                passwordInput.setText("")
                confirmInput.setText("")
                if (signup) {
                    banner.text = "● Approval requested · Administrator review required"
                } else {
                    token = newToken
                    isAdmin = (profile?.optString("role","viewer") ?: "viewer").lowercase() in
                        listOf("owner","admin","administrator","superadmin")
                    accountStatus.text = "● Signed in: " + user +
                        "\nRole: " + profile?.optString("role","viewer") +
                        "\nAccount ID: " + profile?.optString("account_id","unavailable")
                    banner.text = "● Connected · Client Portal"
                    history.clear()
                    messages.removeAllViews()
                    bubble("assistant", "Welcome back, $user. Your desktop AI is available through this private connection.")
                    showTab(0)
                    refreshHome()
                    loadModels()
                }
            }
        }
    }

    private fun signOut() {
        val access = token ?: return
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        token = null; isAdmin = false; sessionId = null
        proposalId = null; proposalHash = null
        history.clear()
        accountStatus.text = "● Signed out"
        homeStatus.text = "Sign in to see your desktop's live status."
        messages.removeAllViews()
        bubble("assistant", "Signed out. Sign in to access Niblit.")
        showTab(3)
        task("Signing out…") {
            try { request(host, access, "/mobile/logout", JSONObject()) }
            finally { runOnUiThread { banner.text = "● Signed out" } }
        }
    }

    private fun refreshHome() {
        val access = token ?: run { homeStatus.text = "Sign in to connect."; return }
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        task("Checking R14 services…") {
            val system = request(host, access, "/mobile/system")
            val sessions = request(host, access, "/mobile/trading/sessions")
            runOnUiThread {
                if (token != access) return@runOnUiThread
                isAdmin = system.optBoolean("demo_controls_available")
                homeStatus.text = if (system.optBoolean("core_online")) {
                    "● Desktop Core connected\nRole: " + system.optString("role","viewer") +
                        "\nMobile backend: " + system.optString("service")
                } else "● Gateway connected · Desktop Core not available"
                updateSessions(sessions)
                banner.text = "● Niblit R14 · Private gateway connected"
            }
        }
    }

    private fun updateSessions(data: JSONObject) {
        val arr = data.optJSONArray("sessions") ?: JSONArray()
        val active = mutableListOf<String>()
        sessionId = null
        for (i in 0 until arr.length()) {
            val row = arr.optJSONObject(i) ?: continue
            if (row.optString("state") == "active") {
                sessionId = row.optString("id")
                active.add(row.optString("symbol") + " · Active")
            }
        }
        sessionStatus.text = if (active.isEmpty()) "No active demo sessions" else active.joinToString("\n")
    }

    private fun refreshSessions() {
        val access = token ?: run { showTab(3); return }
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        task("Refreshing MT5 session…") {
            val data = request(host, access, "/mobile/trading/sessions")
            runOnUiThread { if (token == access) updateSessions(data) }
        }
    }

    private fun loadModels() {
        val access = token ?: return
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        task("Discovering local models…") {
            val data = request(host, access, "/mobile/models")
            val arr = data.optJSONArray("data") ?: JSONArray()
            val found = mutableListOf<String>()
            for (i in 0 until arr.length()) {
                arr.optJSONObject(i)?.optString("id")?.takeIf { it.isNotBlank() }?.let { found.add(it) }
            }
            runOnUiThread {
                if (token != access) return@runOnUiThread
                modelIds.clear(); modelIds.addAll(found)
                (modelSpinner.adapter as ArrayAdapter<*>).notifyDataSetChanged()
                banner.text = "● " + found.size + " local model(s) available"
            }
        }
    }

    private fun sendChat() {
        val access = token ?: run { showTab(3); banner.text = "Sign in first"; return }
        if (busy) return
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        val message = prompt.text.toString().trim()
        val model = modelSpinner.selectedItem?.toString() ?: return
        if (message.isBlank() || message.length > 6000) return
        val turns = JSONArray()
        for ((role, content) in history.takeLast(10)) {
            turns.put(JSONObject().put("role",role).put("content",content))
        }
        turns.put(JSONObject().put("role","user").put("content",message))
        val payload = JSONObject().put("model",model).put("messages",turns).put("max_tokens",512)
        busy = true
        send.isEnabled = false
        prompt.setText("")
        bubble("user",message)
        task("Niblit is thinking…") {
            try {
                val result = request(host,access,"/mobile/chat",payload)
                val reply = result.optJSONArray("choices")?.optJSONObject(0)
                    ?.optJSONObject("message")?.optString("content").orEmpty().ifBlank { "(No response)" }
                runOnUiThread {
                    if (token != access) return@runOnUiThread
                    history.add("user" to message)
                    history.add("assistant" to reply)
                    while (history.size > 24) history.removeAt(0)
                    bubble("assistant",reply)
                    banner.text = "● Answer from " + model
                }
            } finally { runOnUiThread { busy = false; send.isEnabled = true } }
        }
    }

    private fun refreshMarkets() {
        val access = token ?: run { showTab(3); return }
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        task("Refreshing market observations…") {
            val data = request(host,access,"/mobile/observations")
            val arr = data.optJSONArray("observers") ?: JSONArray()
            val found = mutableListOf<String>()
            for (i in 0 until arr.length()) {
                val row = arr.optJSONObject(i) ?: continue
                found.add(row.optString("symbol") + " · " + row.optString("adapter") +
                          " · " + row.optString("side","wait"))
            }
            runOnUiThread {
                if (token != access) return@runOnUiThread
                markets.clear(); markets.addAll(found)
                (marketSpinner.adapter as ArrayAdapter<*>).notifyDataSetChanged()
                marketDetails.text = found.size.toString() + " market observations; no orders implied."
                banner.text = "● Market observations refreshed"
            }
        }
    }

    private fun explainMarket() {
        advisoryText.text = "Use Niblit AI Chat for analysis of verified Market Desk observations. " +
            "Mobile advisory controls must not submit, modify or close broker orders."
        showTab(1)
    }

    private fun scope(): JSONObject {
        fun decimal(field: EditText) =
            field.text.toString().trim().toDouble().also { require(it.isFinite()) }
        fun number(field: EditText) = field.text.toString().trim().toInt()
        return JSONObject().put("symbol",symbol.text.toString().trim())
            .put("volume_lots",decimal(volume)).put("minutes",number(minutes))
            .put("max_trades",number(entries)).put("max_positions",number(positions))
            .put("risk_pct",decimal(riskPercent)).put("risk_cash",decimal(riskCash))
    }

    private fun tradeAction(action: String) {
        val access = token ?: run { banner.text = "Sign in first"; showTab(3); return }
        if (!isAdmin) { banner.text = "Administrator approval required for demo controls"; return }
        val host = try { base() } catch (exc: Exception) { banner.text = exc.message; return }
        val payload = try {
            when (action) {
                "activate" -> JSONObject()
                    .put("id",proposalId ?: error("Propose reviewed settings first"))
                    .put("spec_hash",proposalHash ?: error("Missing proposal fingerprint"))
                "stop" -> JSONObject().put("id",sessionId ?: JSONObject.NULL)
                else -> scope()
            }
        } catch (exc: Exception) { banner.text = exc.message; return }
        if (action in listOf("activate","stop")) {
            AlertDialog.Builder(this)
                .setTitle(if(action=="activate")"Activate MT5 DEMO session?" else "Stop demo session?")
                .setMessage(if(action=="activate")
                    "R14 may submit demo orders only when its strategies and broker rules qualify. Real-money trading is not enabled."
                    else "This prevents further entries. An existing broker-open position may remain under its SL/TP.")
                .setNegativeButton("Cancel",null)
                .setPositiveButton(if(action=="activate")"Activate" else "Stop") { _, _ ->
                    submitTrade(host,access,action,payload)
                }.show()
        } else submitTrade(host,access,action,payload)
    }

    private fun submitTrade(host: String, access: String, action: String, body: JSONObject) {
        task("R14 demo " + action + "…") {
            val result = request(host,access,"/mobile/trading/"+action,body)
            runOnUiThread {
                if (token != access) return@runOnUiThread
                when (action) {
                    "readiness" -> {
                        proposalId = null; proposalHash = null
                        val arr = result.optJSONArray("blockers") ?: JSONArray()
                        val reasons = (0 until arr.length()).joinToString("\n") { i ->
                            arr.optJSONObject(i)?.let { "• " + it.optString("reason") } ?: ""
                        }
                        tradeStatus.text = "Eligible: " + result.optBoolean("activation_eligible") +
                            "\n" + reasons.ifEmpty { "No readiness blockers." }
                    }
                    "propose" -> {
                        proposalId = result.optString("id")
                        proposalHash = result.optString("spec_hash")
                        tradeStatus.text = "Proposed: " + result.optString("symbol") +
                            "\nDuration: " + result.optInt("duration_seconds") +
                            " seconds\nReview the scope, then explicitly activate."
                    }
                    "activate" -> {
                        sessionId = result.optString("id")
                        proposalId = null; proposalHash = null
                        tradeStatus.text = "Demo session: " + result.optString("state") +
                            "\nExpires (Unix): " + result.optDouble("expires")
                    }
                    "stop" -> {
                        sessionId = null
                        tradeStatus.text = "Session: " + result.optString("state") +
                            "\nExisting broker positions may remain protected."
                    }
                }
                banner.text = "● R14 demo " + action + " accepted"
                refreshSessions()
            }
        }
    }

    override fun onDestroy() {
        token = null
        history.clear()
        work.shutdownNow()
        super.onDestroy()
    }
}
