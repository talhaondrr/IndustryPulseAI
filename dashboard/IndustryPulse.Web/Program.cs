using System.Text.Json;
using IndustryPulse.Web.Services;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllersWithViews().AddJsonOptions(options =>
    options.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);
builder.Services.AddHttpClient<PulseApiClient>(client =>
{
    client.BaseAddress = new Uri(builder.Configuration["FastApi:BaseUrl"] ?? "http://127.0.0.1:8000/");
    client.Timeout = TimeSpan.FromSeconds(9);
});
builder.Services.AddHttpClient<MlflowClient>(client =>
{
    client.BaseAddress = new Uri(builder.Configuration["Mlflow:BaseUrl"] ?? "http://127.0.0.1:5000/");
    client.Timeout = TimeSpan.FromSeconds(2);
});

var app = builder.Build();
app.UseRequestLocalization("en-US");
app.UseStaticFiles();
app.MapControllers();
app.Run();
