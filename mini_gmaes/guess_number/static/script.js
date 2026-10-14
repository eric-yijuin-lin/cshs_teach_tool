const $ = id => document.getElementById(id);

const setupForm = $("setupForm");
const setupPanel = $("setupPanel");
const gamePanel = $("gamePanel");
const spinButton = $("spinButton");
const chosenStudent = $("chosenStudent");
const guessForm = $("guessForm");
const guessInput = $("guessInput");
const result = $("result");
const historyList = $("history");
const errorMessage = $("errorMessage");

const canvas = $("wheel");
const ctx = canvas.getContext("2d");

const TAU = Math.PI * 2;

const colors = [
    "#ffca64",
    "#7edbe8",
    "#ff8e8e",
    "#a5e3a1",
    "#c9a0ff",
    "#ffaed7",
    "#82b6ff",
    "#ffe48d"
];

let students = [];
let rotation = 0;
let selectedName = "";
let spinning = false;
let finished = false;


// 與 Python Flask 溝通
async function sendRequest(path, formData = null) {
    const options = {
        method: "POST"
    };

    if (formData !== null) {
        options.body = formData;
    }

    const response = await fetch(path, options);
    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || "操作失敗");
    }

    return data;
}


// 顯示錯誤訊息
function showError(message) {
    errorMessage.textContent = message;
}


// 開始遊戲
setupForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    showError("");

    const submitButton = setupForm.querySelector("button[type='submit']");
    submitButton.disabled = true;

    try {
        const data = await sendRequest(
            "/start",
            new FormData(setupForm)
        );

        students = data.students;
        rotation = 0;
        selectedName = "";
        spinning = false;
        finished = false;

        chosenStudent.textContent = "準備抽出幸運同學！";
        result.textContent = "";
        result.className = "result";
        historyList.replaceChildren();
        guessForm.classList.add("is-hidden");
        spinButton.disabled = false;

        drawWheel();

        setupPanel.classList.add("is-hidden");
        gamePanel.classList.remove("is-hidden");

    } catch (error) {
        showError(error.message);
    } finally {
        submitButton.disabled = false;
    }
});


// 繪製轉盤
function drawWheel() {
    const center = canvas.width / 2;
    const radius = center - 15;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (students.length === 0) {
        return;
    }

    const angle = TAU / students.length;

    for (let i = 0; i < students.length; i++) {
        const start = rotation - Math.PI / 2 + i * angle;
        const end = start + angle;

        // 扇形
        ctx.beginPath();
        ctx.moveTo(center, center);
        ctx.arc(center, center, radius, start, end);
        ctx.closePath();

        ctx.fillStyle = colors[i % colors.length];
        ctx.fill();

        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.stroke();

        // 學生姓名
        ctx.save();

        ctx.translate(center, center);
        ctx.rotate(start + angle / 2);

        ctx.fillStyle = "#20243b";
        ctx.font = students.length > 25
            ? "bold 16px sans-serif"
            : "bold 22px sans-serif";

        ctx.textAlign = "right";
        ctx.textBaseline = "middle";

        let name = students[i];

        if (name.length > 7) {
            name = name.slice(0, 6) + "…";
        }

        ctx.fillText(name, radius - 28, 0, radius * 0.62);

        ctx.restore();
    }

    // 中心圓
    ctx.beginPath();
    ctx.arc(center, center, 40, 0, TAU);
    ctx.fillStyle = "#ffffff";
    ctx.fill();

    ctx.beginPath();
    ctx.arc(center, center, 29, 0, TAU);
    ctx.fillStyle = "#303c75";
    ctx.fill();
}


// 轉盤動畫
function animateWheel(index) {
    return new Promise(resolve => {
        const startRotation = rotation;
        const angle = TAU / students.length;

        // 讓指定學生停在上方指針位置
        const target = -(index + 0.5) * angle;

        const offset =
            ((target - (startRotation % TAU)) % TAU + TAU) % TAU;

        const endRotation = startRotation + TAU * 6 + offset;
        const duration = 4600;

        let startTime = null;

        function frame(time) {
            if (startTime === null) {
                startTime = time;
            }

            const progress = Math.min(
                (time - startTime) / duration,
                1
            );

            const easing = 1 - Math.pow(1 - progress, 4);

            rotation = startRotation +
                (endRotation - startRotation) * easing;

            drawWheel();

            if (progress < 1) {
                requestAnimationFrame(frame);
            } else {
                rotation = endRotation % TAU;
                drawWheel();
                resolve();
            }
        }

        requestAnimationFrame(frame);
    });
}


// 抽出學生
spinButton.addEventListener("click", async function () {
    if (spinning || finished) {
        return;
    }

    spinning = true;
    spinButton.disabled = true;

    guessForm.classList.add("is-hidden");
    chosenStudent.textContent = "🎲 命運轉動中...";
    result.textContent = "";
    showError("");

    try {
        const data = await sendRequest("/spin");

        await animateWheel(data.index);

        selectedName = data.name;

        chosenStudent.textContent =
            "🎤 " + selectedName + "，換你猜！";

        guessInput.value = "";
        guessForm.classList.remove("is-hidden");
        guessInput.focus();

    } catch (error) {
        showError(error.message);
    } finally {
        spinning = false;

        if (!finished) {
            spinButton.disabled = false;
        }
    }
});


// 送出猜測
guessForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    showError("");

    const guessButton = guessForm.querySelector("button[type='submit']");
    guessButton.disabled = true;

    try {
        const data = await sendRequest(
            "/guess",
            new FormData(guessForm)
        );

        result.textContent = data.message;
        result.className = "result";

        // 更新歷史紀錄
        historyList.replaceChildren();

        const records = [...data.history].reverse();

        for (const record of records) {
            const li = document.createElement("li");

            li.textContent =
                record.name +
                " 猜 " +
                record.guess +
                " → " +
                record.message;

            historyList.appendChild(li);
        }

        if (data.winner) {
            finished = true;
            spinButton.disabled = true;
            guessForm.classList.add("is-hidden");
            result.classList.add("isSuccess");

            showWinner(data.winner);
        } else {
            guessForm.classList.add("is-hidden");
            chosenStudent.textContent =
                data.name + "，感謝你的挑戰！";
        }

    } catch (error) {
        showError(error.message);
    } finally {
        guessButton.disabled = false;
    }
});


// 顯示獲勝動畫
function showWinner(name) {
    const overlay = $("winnerOverlay");
    const confetti = $("confetti");

    $("winnerName").textContent = name;
    confetti.replaceChildren();

    overlay.classList.remove("is-hidden");

    for (let i = 0; i < 120; i++) {
        const piece = document.createElement("span");

        piece.className = "confettiPiece";

        piece.style.left = Math.random() * 100 + "%";

        piece.style.backgroundColor =
            colors[Math.floor(Math.random() * colors.length)];

        piece.style.animationDelay =
            Math.random() * 1.5 + "s";

        piece.style.animationDuration =
            2.5 + Math.random() * 2 + "s";

        confetti.appendChild(piece);
    }
}


// 關閉獲勝畫面
$("closeWinner").addEventListener("click", function () {
    $("winnerOverlay").classList.add("is-hidden");
});


// 返回教師設定
$("backButton").addEventListener("click", function () {
    gamePanel.classList.add("is-hidden");
    setupPanel.classList.remove("is-hidden");

    $("answer").value = "";
    showError("");
});