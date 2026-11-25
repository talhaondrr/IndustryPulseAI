using System.ComponentModel.DataAnnotations;
using IndustryPulse.Web.Models;
using IndustryPulse.Web.Services;

namespace IndustryPulse.Web.ViewModels;

public sealed record Page<T>(T? Data, string? Error) where T : class;
public sealed record OverviewModel(Page<Summary> Summary, Page<List<ComponentHealth>> Health);
public sealed record PredictionPage(PredictionInput Input, Prediction? Result = null, string? Error = null);
public sealed record AnalyticsPage(Page<ModelAnalytics> Metrics, TrackingStatus Tracking);

public sealed class PredictionInput
{
    [Required, RegularExpression("^[LMH]$")]
    public string? Type { get; set; }
    [Required, Range(double.Epsilon, 3.4028234663852886e38)]
    public double? AirTemperature { get; set; }
    [Required, Range(double.Epsilon, 3.4028234663852886e38)]
    public double? ProcessTemperature { get; set; }
    [Required, Range(0, int.MaxValue)]
    public int? RotationalSpeed { get; set; }
    [Required, Range(0, 3.4028234663852886e38)]
    public double? Torque { get; set; }
    [Required, Range(0, int.MaxValue)]
    public int? ToolWear { get; set; }
}
