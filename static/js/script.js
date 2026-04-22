document.addEventListener("DOMContentLoaded", function() {
    console.log("FinFlow Loaded");
});
// -------------------- GROWTH CHART --------------------
function drawGrowthChart(portfolio) {

    if (portfolio.length === 0) return;

    const promises = portfolio.map(stock =>
        fetch(`/watchlist-data/${stock.ticker}`).then(res => res.json())
    );

    Promise.all(promises).then(results => {

        const length = results[0].chart.length;
        let totalSeries = new Array(length).fill(0);

        results.forEach((data, i) => {
            if (!data || !data.chart) return;

            for (let j = 0; j < length; j++) {
                totalSeries[j] += data.chart[j] * portfolio[i].qty;
            }
        });

        const ctx = document.getElementById("growthChart");

        if (window.growthChartObj) {
            window.growthChartObj.destroy();
        }

        window.growthChartObj = new Chart(ctx, {
            type: 'line',
            data: {
                labels: Array(length).fill(""),
                datasets: [{
                    data: totalSeries,
                    borderColor: 'green',
                    tension: 0.3,
                    fill: false
                }]
            },
            options: {
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: { display: false }
                }
            }
        });

    });
}