import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const base = process.env.DASHBOARD_URL ?? "http://127.0.0.1:5080";
const browser = process.env.CHROME_BIN ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const offline = process.argv.includes("--offline");
const verifyMlflow = process.argv.includes("--mlflow");
const mlflowOnly = process.argv.includes("--mlflow-only");
const portfolio = process.argv.includes("--portfolio");
const work = resolve("tmp");
await mkdir(work, { recursive: true });
const profile = await mkdtemp(resolve(work, "dashboard-chrome-"));
const chrome = spawn(browser, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--remote-debugging-port=0",
    "--user-data-dir=" + profile, "about:blank"
], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });

let socket;
try {
    const port = await new Promise((done, fail) => {
        let output = "";
        const timeout = setTimeout(() => fail(new Error("Chrome debugger did not start")), 15000);
        chrome.on("error", fail);
        chrome.stderr.on("data", chunk => {
            output += chunk;
            const match = output.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)/);
            if (match) { clearTimeout(timeout); done(match[1]); }
        });
    });
    const targets = await (await fetch("http://127.0.0.1:" + port + "/json/list")).json();
    socket = new WebSocket(targets.find(target => target.type === "page").webSocketDebuggerUrl);
    await new Promise((done, fail) => {
        socket.addEventListener("open", done, { once: true });
        socket.addEventListener("error", fail, { once: true });
    });

    let next = 0;
    const pending = new Map();
    socket.addEventListener("message", event => {
        const message = JSON.parse(event.data);
        if (!pending.has(message.id)) return;
        const { done, fail } = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) fail(new Error(message.error.message));
        else done(message.result);
    });
    const command = (method, params = {}) => new Promise((done, fail) => {
        const id = ++next;
        pending.set(id, { done, fail });
        socket.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
        const reply = await command("Runtime.evaluate", { expression, returnByValue: true });
        if (reply.exceptionDetails) throw new Error(reply.exceptionDetails.text);
        return reply.result.value;
    };
    const until = async (expression, attempts = 40) => {
        for (let i = 0; i < attempts; i++) {
            if (await evaluate(expression)) return;
            await delay(250);
        }
        throw new Error("Browser condition timed out: " + expression);
    };
    async function visit(path, heading) {
        const nav = await command("Page.navigate", { url: base + path });
        assert.equal(nav.errorText, undefined);
        await until("document.readyState === 'complete' && document.querySelector('h1')?.textContent === " + JSON.stringify(heading));
    }
    async function screenshot(name) {
        const image = await command("Page.captureScreenshot", { format: "png" });
        await writeFile(resolve(work, name), Buffer.from(image.data, "base64"));
    }

    async function portfolioShot(name) {
        await mkdir(resolve("docs/screenshots"), { recursive: true });
        const image = await command("Page.captureScreenshot", { format: "png" });
        await writeFile(resolve("docs/screenshots", name + ".png"), Buffer.from(image.data, "base64"));
    }

    const pages = [
        ["/", "Overview", 1], ["/sensor-monitor", "Sensor Monitor", 4],
        ["/ai-prediction", "AI Prediction", 0], ["/model-analytics", "Model Analytics", 2],
        ["/data-pipeline", "Data Pipeline", 0], ["/system-health", "System Health", 0]
    ];
    if (portfolio) {
        await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
        for (const [path, heading, charts] of pages) {
            if (path === "/ai-prediction") continue;
            await visit(path, heading);
            assert.equal(await evaluate("Object.keys(window.Chart?.instances || {}).length"), charts);
            await portfolioShot(path === "/" ? "overview" : path.slice(1));
        }
        await command("Page.navigate", { url: "http://127.0.0.1:8000/docs" });
        await until("document.querySelector('.swagger-ui .opblock') !== null");
        await portfolioShot("fastapi-swagger");
        await visit("/ai-prediction", "AI Prediction");
    } else if (mlflowOnly) {
        await visit("/model-analytics", "Model Analytics");
    } else if (offline) {
        for (const [path, heading] of pages) {
            await visit(path, heading);
            if (path !== "/ai-prediction") assert.match(await evaluate("document.body.innerText"), /API is unreachable/);
        }
        await visit("/ai-prediction", "AI Prediction");
    } else {
        for (const [width, height] of [[1440, 900], [390, 844]]) {
            await command("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 500 });
            for (const [path, heading, charts] of pages) {
                await visit(path, heading);
                assert.equal(await evaluate("document.querySelectorAll('nav [aria-current=page]').length"), 1);
                assert.equal(await evaluate("Object.keys(window.Chart?.instances || {}).length"), charts);
                assert.ok(await evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), heading + " overflows");
                if (path === "/") await screenshot(width > 500 ? "dashboard-desktop.png" : "dashboard-mobile.png");
            }
            console.log(width + " px: six pages, active navigation, expected charts and no horizontal page overflow.");
        }
        await visit("/sensor-monitor", "Sensor Monitor");
        assert.equal(await evaluate("document.querySelectorAll('#sensor-rows tr').length"), 30);
        await until("document.querySelector('#feed-status').textContent.includes('No new stored events')", 90);
        await visit("/ai-prediction", "AI Prediction");
    }

    if (!mlflowOnly) await evaluate(`(() => {
        const form = document.querySelector("form");
        for (const [key, val] of Object.entries({Type:"L", AirTemperature:"300", ProcessTemperature:"310", RotationalSpeed:"1300", Torque:"70", ToolWear:"220"})) {
            form.elements.namedItem("Input." + key).value = val;
        }
        form.requestSubmit();
        return true;
    })()`);
    if (mlflowOnly) {
        assert.ok(await evaluate("document.body.innerText.includes('Cross-validation')"));
    } else if (offline) {
        await until("document.body.innerText.includes('API is unreachable')");
        console.log("Offline: all pages remained usable and the prediction form showed the connection error.");
    } else {
        await until("document.body.innerText.includes('0.998672')");
        assert.match(await evaluate("document.body.innerText"), /Failure flagged[\s\S]*Model version[\s\S]*1\.0\.0/);
        if (portfolio) await portfolioShot("ai-prediction");
        console.log("Online: saved readings refreshed truthfully and the MVC form received the real XGBoost score.");
    }
    if (verifyMlflow || mlflowOnly || portfolio) {
        await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
        await visit("/model-analytics", "Model Analytics");
        assert.match(await evaluate("document.body.innerText"), /IndustryPulse-XGBoost Registry version\s+v\d+/);
        const link = await evaluate("[...document.links].find(item => item.textContent.includes('Open MLflow tracking')).href");
        assert.match(link, /^http:\/\/127\.0\.0\.1:5000\/#\/experiments\/\d+/);
        await command("Page.navigate", { url: link });
        await until("[...document.querySelectorAll('a,button')].some(item => item.textContent.trim() === 'Training runs')");
        await evaluate("[...document.querySelectorAll('a,button')].find(item => item.textContent.trim() === 'Training runs').click()");
        try {
            await until("['XGBoost', 'Random Forest', 'MLP', 'SVM', 'Logistic Regression', 'Decision Tree', 'Dummy Classifier'].every(name => document.body?.innerText.includes(name + ' · cross_validation'))", 50);
        } catch (error) {
            console.error(await evaluate("document.body?.innerText.slice(0, 3000)"));
            throw error;
        }
        assert.ok(await evaluate("document.body.innerText.includes('XGBoost · independent_test')"));
        if (portfolio) await portfolioShot("mlflow");
        console.log("MLflow UI: seven cross-validation runs and the separate XGBoost holdout run are visible.");
    }
} finally {
    socket?.close();
    chrome.kill();
    await delay(500);
    await rm(profile, { recursive: true, force: true }).catch(() => {});
}
