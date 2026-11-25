using IndustryPulse.Web.Models;
using IndustryPulse.Web.Services;
using IndustryPulse.Web.ViewModels;
using Microsoft.AspNetCore.Mvc;

namespace IndustryPulse.Web.Controllers;

public sealed class DashboardController(PulseApiClient api, MlflowClient tracking) : Controller
{
    [HttpGet("/")]
    public async Task<IActionResult> Overview(CancellationToken token)
    {
        var summary = api.Get<Summary>("analytics/summary", token);
        var health = api.Get<List<ComponentHealth>>("analytics/health", token);
        await Task.WhenAll(summary, health);
        return View(new OverviewModel(await summary, await health));
    }

    [HttpGet("/sensor-monitor")]
    public async Task<IActionResult> Sensors(CancellationToken token) =>
        View(await api.Get<SensorFeed>("analytics/sensors", token));

    [HttpGet("/sensor-monitor/feed")]
    [ResponseCache(NoStore = true, Location = ResponseCacheLocation.None)]
    public async Task<IActionResult> SensorFeed(CancellationToken token)
    {
        var result = await api.Get<SensorFeed>("analytics/sensors", token);
        return result.Data is null ? StatusCode(503, new { error = result.Error }) : Json(result.Data);
    }

    [HttpGet("/ai-prediction")]
    public IActionResult Predict() => View(new PredictionPage(new PredictionInput()));

    [HttpPost("/ai-prediction")]
    [ValidateAntiForgeryToken]
    public async Task<IActionResult> Predict([Bind(Prefix = "Input")] PredictionInput input, CancellationToken token)
    {
        if (!ModelState.IsValid)
            return View(new PredictionPage(input));
        var result = await api.Predict(input, token);
        return View(new PredictionPage(input, result.Data, result.Error));
    }

    [HttpGet("/model-analytics")]
    public async Task<IActionResult> Analytics(CancellationToken token)
    {
        var metrics = api.Get<ModelAnalytics>("analytics/models", token);
        var registry = tracking.GetStatus(token);
        await Task.WhenAll(metrics, registry);
        return View(new AnalyticsPage(await metrics, await registry));
    }

    [HttpGet("/data-pipeline")]
    public async Task<IActionResult> Pipeline(CancellationToken token) =>
        View(await api.Get<Summary>("analytics/summary", token));

    [HttpGet("/system-health")]
    public async Task<IActionResult> Health(CancellationToken token) =>
        View(await api.Get<List<ComponentHealth>>("analytics/health", token));
}
