document.addEventListener('DOMContentLoaded', () => {
    // --- Configuration & State ---
    const inputs = {
        retirementAge: { el: document.getElementById('retirementAge'), slider: document.getElementById('retirementAgeSlider') },
        brokerageBalance: { el: document.getElementById('brokerageBalance'), slider: document.getElementById('brokerageBalanceSlider') },
        retirementBalance: { el: document.getElementById('retirementBalance'), slider: document.getElementById('retirementBalanceSlider') },
        monthlyIncome: { el: document.getElementById('monthlyIncome'), slider: document.getElementById('monthlyIncomeSlider') },
        monthlyVaDisability: { el: document.getElementById('monthlyVaDisability'), slider: document.getElementById('monthlyVaDisabilitySlider') },
        monthlyCoastIncome: { el: document.getElementById('monthlyCoastIncome'), slider: document.getElementById('monthlyCoastIncomeSlider') },
        coastEndAge: { el: document.getElementById('coastEndAge'), slider: document.getElementById('coastEndAgeSlider') },
        savingsAllocation: { el: document.getElementById('savingsAllocation'), slider: document.getElementById('savingsAllocationSlider') },
        max401k: { el: document.getElementById('max401k'), slider: null },
        monthlySpending: { el: document.getElementById('monthlySpending'), slider: document.getElementById('monthlySpendingSlider') },
        returnPre: { el: document.getElementById('returnPre'), slider: document.getElementById('returnPreSlider') },
        returnPost: { el: document.getElementById('returnPost'), slider: document.getElementById('returnPostSlider') }
    };

    // Fixed values
    const currentAgeVal = 40;
    const deathAgeVal = 95;
    const ANNUAL_401K_LIMIT = 23500;

    const results = {
        fireNumber: document.getElementById('fireNumberValue'),
        yearsToFi: document.getElementById('yearsToFiValue'),
        success: document.getElementById('successValue'),
        successSubtext: document.getElementById('successSubtext')
    };

    let chartInstance = null;

    // --- utility formatters ---
    const formatMoney = (num) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(num);

    // --- Initialization ---
    function init() {
        // Sync Inputs and Sliders
        for (const key in inputs) {
            const { el, slider } = inputs[key];
            if (!el) continue; // max401k has no slider

            if (key === 'max401k') {
                el.addEventListener('change', () => {
                    toggleSavingsSlider(el.checked);
                    calculateAndRender();
                });
                continue;
            }

            if (!slider) {
                console.error(`Missing input element for ${key}`);
                continue;
            }

            slider.addEventListener('input', () => {
                el.value = slider.value;
                calculateAndRender();
            });

            el.addEventListener('input', () => {
                slider.value = el.value;
                calculateAndRender();
            });
        }

        // Add special validation for Ages
        inputs.retirementAge.el.addEventListener('change', validateAges);
        inputs.coastEndAge.el.addEventListener('change', validateAges);

        // Initial Calculation
        toggleSavingsSlider(inputs.max401k.el.checked);
        calculateAndRender();
    }

    function toggleSavingsSlider(disabled) {
        inputs.savingsAllocation.el.disabled = disabled;
        inputs.savingsAllocation.slider.disabled = disabled;
        const group = inputs.savingsAllocation.slider.closest('.input-group');
        if (group) group.style.opacity = disabled ? '0.5' : '1';
    }

    function validateAges() {
        let retire = parseInt(inputs.retirementAge.el.value);
        let coastEnd = parseInt(inputs.coastEndAge.el.value);

        if (retire <= currentAgeVal) {
            retire = currentAgeVal + 1;
            inputs.retirementAge.el.value = retire;
            inputs.retirementAge.slider.value = retire;
        }

        // Coast end age logic
        if (coastEnd > deathAgeVal) {
            coastEnd = deathAgeVal;
            inputs.coastEndAge.el.value = coastEnd;
            inputs.coastEndAge.slider.value = coastEnd;
        }

        calculateAndRender();
    }

    function calculateFIRE() {
        const currentAge = currentAgeVal;
        const retirementAge = parseInt(inputs.retirementAge.el.value);
        const deathAge = deathAgeVal;
        const coastEndAge = parseInt(inputs.coastEndAge.el.value);
        const max401k = inputs.max401k.el.checked;

        let brokerage = parseFloat(inputs.brokerageBalance.el.value);
        let retirement = parseFloat(inputs.retirementBalance.el.value);

        // Convert Monthly to Annual
        const income = parseFloat(inputs.monthlyIncome.el.value) * 12;
        const vaDisability = parseFloat(inputs.monthlyVaDisability.el.value) * 12;
        const coastIncomeAmt = parseFloat(inputs.monthlyCoastIncome.el.value) * 12;
        const spending = parseFloat(inputs.monthlySpending.el.value) * 12;

        const savingsAllocPercent = parseFloat(inputs.savingsAllocation.el.value) / 100; // % to Brokerage

        const returnPre = parseFloat(inputs.returnPre.el.value) / 100;
        const returnPost = parseFloat(inputs.returnPost.el.value) / 100;

        // Basic FIRE Number (Net Invested Assets needed to support spending solely from portfolio)
        // Note: With VA Disability/Coast Income, the "Number" is dynamic.
        // Classic FIRE number is 25x Full Spending.
        // Adjusted FIRE number is 25x (Spending - PermanentIncome).
        // Since VA is permanent and tax-free (assumed), we can subtract it from spending need.
        const adjustedSpendingNeed = Math.max(0, spending - vaDisability);
        const fireNumber = adjustedSpendingNeed * 25;

        const labels = [];
        const brokerageData = [];
        const retirementData = [];
        const totalData = [];

        let fiAge = null;
        let bridgeFailed = false;
        let success = true;

        let age = currentAge;

        while (age <= deathAge) {
            const totalNetWorth = brokerage + retirement;

            labels.push(age);
            brokerageData.push(brokerage);
            retirementData.push(retirement);
            // We'll calculate total data client-side for chart if needed, or push here

            // Check FI
            if (fiAge === null && totalNetWorth >= fireNumber && age >= currentAge) {
                fiAge = age;
            }

            // --- SIMULATION STEP ---
            const rate = (age < retirementAge) ? returnPre : returnPost;

            // Apply Growth First (Simplified start-of-year or end-of-year? Let's do End of Year logic for contributions/withdrawals to be simpler, 
            // but usually growth applies to balance at start).
            // Let's do: Balance Start -> Growth -> +/- Cashflow -> Balance End
            brokerage += brokerage * rate;
            retirement += retirement * rate;

            // Determine Cashflow
            if (age < retirementAge) {
                // Accumulation
                // Total Income = Job + VA (Coast usually applies after leaving main job, but user might have side hustle. logic: COAST applies in retirement)
                const totalIncome = income + vaDisability;
                const surplus = totalIncome - spending;

                if (surplus > 0) {
                    let toRetirement = 0;
                    let toBrokerage = 0;

                    if (max401k) {
                        // Max 401k Priority
                        toRetirement = Math.min(surplus, ANNUAL_401K_LIMIT);
                        toBrokerage = Math.max(0, surplus - toRetirement);
                    } else {
                        // Percentage Split
                        toBrokerage = surplus * savingsAllocPercent;
                        toRetirement = surplus * (1 - savingsAllocPercent);
                    }

                    brokerage += toBrokerage;
                    retirement += toRetirement;
                } else {
                    // Deficit while working?? Assume eating into Brokerage first.
                    let deficit = Math.abs(surplus);
                    if (brokerage >= deficit) {
                        brokerage -= deficit;
                    } else {
                        deficit -= brokerage;
                        brokerage = 0;
                        retirement -= deficit; // Penetrating retirement early (with penalty? ignoring for simplicity)
                    }
                }
            } else {
                // Decumulation (Retirement)
                let currentIncome = vaDisability;

                // Add Coast Income if eligible
                if (age < coastEndAge) {
                    currentIncome += coastIncomeAmt;
                }

                const netNeed = spending - currentIncome;

                if (netNeed > 0) {
                    // We need to withdraw 'netNeed' from portfolio
                    let amountNeeded = netNeed;

                    // STRATEGY: 
                    // 1. If Age < 59.5, MUST pull from Brokerage to avoid penalty.
                    //    If Brokerage empty, we have a "Bridge Failure" (or penalty withdrawal).
                    //    We will pull from Retirement but flag it.
                    // 2. If Age >= 59.5, pull from Brokerage first (FIFO/Taxable) then Retirement?
                    //    Or Proportional?
                    //    Standard: Brokerage First.

                    if (brokerage >= amountNeeded) {
                        brokerage -= amountNeeded;
                    } else {
                        // Brokerage empty or insufficient
                        const fromBrokerage = brokerage;
                        brokerage = 0;
                        const remaining = amountNeeded - fromBrokerage;

                        // Check Bridge Failure
                        if (age < 60 && !bridgeFailed && fromBrokerage < amountNeeded) {
                            // Using 60 as rough 59.5 proxy since we use integer ages
                            // If we touch retirement before 60, it's a bridge gap?
                            // Strictly speaking, you can access 401k at 55 (Rule of 55) or 72t.
                            // But for a FIRE calculator, usually you want to see if Brokerage covers it.
                            // Let's just withdraw from Retirement but NOT explicitly fail the whole plan, 
                            // just maybe visually indicate it?
                            // For this logic, we just withdraw from retirement.
                        }

                        retirement -= remaining;
                    }
                } else {
                    // Surplus in retirement (Income > Spending)
                    // Add to Brokerage (Taxable)
                    brokerage += Math.abs(netNeed);
                }
            }

            // Check Solvency
            if (retirement < 0) retirement = 0;
            // Since we zeroed brokerage above, we need to check total
            if ((brokerage + retirement) <= 0 && success && age < deathAge) {
                success = false; // Ran out of money
            }

            age++;
        }

        const finalAmount = brokerageData[brokerageData.length - 1] + retirementData[retirementData.length - 1];

        return {
            results: {
                fireNumber,
                fiAge,
                success,
                finalAmount
            },
            chartData: {
                labels,
                brokerageData,
                retirementData
            }
        };
    }

    function updateUI(calcData) {
        const currentAge = currentAgeVal;

        results.fireNumber.textContent = formatMoney(calcData.results.fireNumber);

        if (calcData.results.fiAge) {
            results.yearsToFi.textContent = Math.max(0, calcData.results.fiAge - currentAge);
        } else {
            results.yearsToFi.textContent = "Never";
        }

        if (calcData.results.success) {
            results.success.textContent = "Success";
            results.success.style.color = "#4ade80";
            results.successSubtext.textContent = `Ending Balance: ${formatMoney(calcData.results.finalAmount)}`;
        } else {
            results.success.textContent = "Depleted";
            results.success.style.color = "#f87171";
            results.successSubtext.textContent = "Portfolio ran out";
        }
    }

    function renderChart(chartData, fireNumber) {
        const ctxElement = document.getElementById('fireChart');
        if (!ctxElement) return;
        if (typeof Chart === 'undefined') return "Chart.js not loaded";
        if (chartInstance) chartInstance.destroy();

        // Custom Plugin for Vertical Retirement Line
        const retirementLinePlugin = {
            id: 'retirementLine',
            afterDraw: (chart) => {
                const retirementAgeVal = parseInt(inputs.retirementAge.el.value);
                if (!retirementAgeVal) return;

                const ctx = chart.ctx;
                const xAxis = chart.scales.x;
                const yAxis = chart.scales.y;

                // Find the x-coordinate for the retirement age
                // We need to match the age to the label index, or use getPixelForValue if linear/category
                // Since labels are just ages [40, 41, ...], we can try getPixelForValue
                const x = xAxis.getPixelForValue(retirementAgeVal);

                if (x >= xAxis.left && x <= xAxis.right) {
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(x, yAxis.top);
                    ctx.lineTo(x, yAxis.bottom);
                    ctx.lineWidth = 2;
                    ctx.strokeStyle = '#f472b6'; // Pink-400
                    ctx.setLineDash([5, 5]);
                    ctx.stroke();

                    // Label
                    ctx.fillStyle = '#f472b6';
                    ctx.textAlign = 'center';
                    ctx.font = '12px Inter';
                    ctx.fillText('Retirement', x, yAxis.top - 10);
                    ctx.restore();
                }
            }
        };

        chartInstance = new Chart(ctxElement.getContext('2d'), {
            type: 'line',
            data: {
                labels: chartData.labels,
                datasets: [
                    {
                        label: 'FIRE Goal',
                        data: Array(chartData.labels.length).fill(fireNumber),
                        borderColor: '#4ade80', // Green
                        borderWidth: 2,
                        borderDash: [5, 5],
                        pointRadius: 0,
                        fill: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#94a3b8' } },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function (context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: false, // X is shared
                        grid: { color: '#334155', drawBorder: false },
                        ticks: { color: '#94a3b8' }
                    },
                    y: {
                        stacked: true, // IMPORTANT: Stack the areas
                        grid: { color: '#334155', drawBorder: false },
                        ticks: {
                            color: '#94a3b8',
                            callback: function (value) { return '$' + value / 1000 + 'k'; }
                        }
                    }
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                }
            }
        });
    }

    function calculateAndRender() {
        const data = calculateFIRE();
        updateUI(data);
        renderChart(data.chartData, data.results.fireNumber);
    }

    init();
});
