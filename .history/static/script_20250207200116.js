document.addEventListener("DOMContentLoaded", function () {
    const essayForm = document.getElementById("essay-form");

    if (essayForm) {
        essayForm.addEventListener("submit", function (event) {
            event.preventDefault(); // Prevent default form submission

            const essayText = document.getElementById("essay").value;
            const contextText = document.getElementById("context").value;

            if (!contextText.trim()) {
                alert("Error: Please provide context for grading.");
                return;
            }

            fetch("/set_criteria", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ essay: essayText, context: contextText }),
            })
            .then(response => {
                if (response.redirected) {
                    window.location.href = response.url; // Redirect to /set_criteria
                } else {
                    return response.json();
                }
            })
            .catch(error => {
                console.error("Error processing essay:", error);
                alert("An error occurred while processing the essay.");
            });
        });
    }
});