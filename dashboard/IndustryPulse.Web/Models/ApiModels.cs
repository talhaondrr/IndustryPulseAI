namespace IndustryPulse.Web.Models;

public sealed record Summary(long ProductTypes, long SensorRecords, long FailureRecords,
    long TrainingRecords, long Failures, long Normal, long? StreamEvents, double CountQueryMs,
    EtlBenchmark? EtlBenchmark)
{
    public double FailureRate => TrainingRecords == 0 ? 0 : 100.0 * Failures / TrainingRecords;
}

public sealed record EtlBenchmark(double DurationMs, long Records, DateTimeOffset MeasuredAt);

public sealed record SensorEvent(Guid EventId, DateTimeOffset EventTime, string ProductType,
    double AirTemperature, double ProcessTemperature, int RotationalSpeed, double Torque, int ToolWear);

public sealed record SensorFeed(bool TableAvailable, List<SensorEvent> Readings);
public sealed record ComponentHealth(string Name, string Status, string Detail);
public sealed record Metrics(string Model, double Accuracy, double BalancedAccuracy,
    double Precision, double Recall, double F1, double RocAuc, double AveragePrecision);
public sealed record Holdout(string Model, double Accuracy, double BalancedAccuracy,
    double Precision, double Recall, double F1, double RocAuc, double AveragePrecision,
    int Tn, int Fp, int Fn, int Tp);
public sealed record EpochLoss(int Epoch, double Loss);
public sealed record ModelAnalytics(List<Metrics> CrossValidation, Holdout IndependentTest,
    List<EpochLoss> MlpTrainingLoss);

public sealed record Prediction(int PredictedClass, double FailureScore, double DecisionThreshold,
    string ModelVersion, DateTimeOffset PredictionTimestamp);
