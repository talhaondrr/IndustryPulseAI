using System.Net;
using System.Text.Json;

namespace IndustryPulse.Web.Services;

public sealed record TrackingStatus(string Url, string Message, string? Version = null,
    string? DeploymentVersion = null);

public sealed class MlflowClient(HttpClient client)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    public async Task<TrackingStatus> GetStatus(CancellationToken token)
    {
        var root = client.BaseAddress!.AbsoluteUri;
        try
        {
            using var versionResponse = await client.GetAsync("api/2.0/mlflow/registered-models/alias?name=IndustryPulse-XGBoost&alias=verified", token);
            using var experimentResponse = await client.GetAsync("api/2.0/mlflow/experiments/get-by-name?experiment_name=IndustryPulseAI", token);
            if (experimentResponse.IsSuccessStatusCode)
            {
                var item = await experimentResponse.Content.ReadFromJsonAsync<ExperimentEnvelope>(Json, token);
                if (item?.Experiment?.ExperimentId is { } experimentId)
                    root += "#/experiments/" + Uri.EscapeDataString(experimentId);
            }
            if (versionResponse.IsSuccessStatusCode)
            {
                var entry = await versionResponse.Content.ReadFromJsonAsync<VersionEnvelope>(Json, token);
                var model = entry?.ModelVersion;
                if (model?.Status == "READY" && model.Tags?.Any(tag => tag is { Key: "verification", Value: "verified" }) == true)
                    return new(root, "Registered model verified against the local pipeline.", model.Version,
                        model.Tags.FirstOrDefault(tag => tag.Key == "deployment_model_version")?.Value);
            }
            if (versionResponse.IsSuccessStatusCode || versionResponse.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.BadRequest)
                return new(root, "MLflow responded. A verified Registry version is not available yet.");
        }
        catch (OperationCanceledException) when (!token.IsCancellationRequested) { }
        catch (Exception error) when (error is HttpRequestException or JsonException) { }
        return new(root, "MLflow is unavailable. Published model results remain accessible.");
    }

    private sealed record ExperimentEnvelope(ExperimentInfo? Experiment);
    private sealed record ExperimentInfo(string ExperimentId);
    private sealed record VersionEnvelope(VersionInfo? ModelVersion);
    private sealed record VersionInfo(string Version, string Status, List<VersionTag>? Tags);
    private sealed record VersionTag(string Key, string Value);
}
