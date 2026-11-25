using System.Net;
using System.Text.Json;
using IndustryPulse.Web.Models;
using IndustryPulse.Web.ViewModels;

namespace IndustryPulse.Web.Services;

public sealed class PulseApiClient(HttpClient client, ILogger<PulseApiClient> logger)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    public Task<Page<T>> Get<T>(string path, CancellationToken token) where T : class =>
        Read<T>(() => client.GetAsync(path, token), token);

    public Task<Page<Prediction>> Predict(PredictionInput input, CancellationToken token) =>
        Read<Prediction>(() => client.PostAsJsonAsync("predict", input, Json, token), token);

    private async Task<Page<T>> Read<T>(Func<Task<HttpResponseMessage>> send, CancellationToken token)
        where T : class
    {
        try
        {
            using var response = await send();
            if (response.IsSuccessStatusCode)
            {
                var data = await response.Content.ReadFromJsonAsync<T>(Json, token);
                return data is not null ? new(data, null) : new(null, "The API returned no data.");
            }
            return new(null, response.StatusCode switch
            {
                HttpStatusCode.UnprocessableEntity => "Check the sensor values and try again.",
                HttpStatusCode.ServiceUnavailable => "The API responded, but this data or model is temporarily unavailable.",
                _ => "The API could not complete this request. Try again."
            });
        }
        catch (OperationCanceledException) when (!token.IsCancellationRequested)
        {
            return new(null, "The API did not respond in time. Try again.");
        }
        catch (Exception error) when (error is HttpRequestException or JsonException)
        {
            logger.LogWarning("Dashboard API request failed ({ErrorType}).", error.GetType().Name);
            return new(null, "The API is unreachable or returned unreadable data. Check the FastAPI service and try again.");
        }
    }
}
