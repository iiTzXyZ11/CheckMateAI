document.addEventListener("DOMContentLoaded", function () {
    const essayForm = document.getElementById("essay-form");

    if (essayForm) {
        essayForm.addEventListener("submit", function (event) {
            event.preventDefault(); // Prevent default form submission

            const essayText = document.getElementById("essay").value.trim();
            const contextText = document.getElementById("context").value.trim();
            const fileInput = document.querySelector('input[type="file"]');

            let isFromImage = fileInput.files.length > 0;

            // Validate word count only if text is manually entered (not from OCR)
            if (!isFromImage && essayText.split(/\s+/).length < 20) {
                alert("Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita.");
                return;
            }

            // Ensure context is provided
            if (!contextText) {
                alert("Error: Please provide context for grading.");
                return;
            }

            // Create a FormData object to send text and image data
            const formData = new FormData();
            formData.append("essay", essayText);
            formData.append("context", contextText);
            if (isFromImage) {
                formData.append("image", fileInput.files[0]); // Include image file if uploaded
            }

            // Redirect to `/set_criteria` after submitting
            fetch("/set_criteria", {
                method: "POST",
                body: formData
            })
            .then(response => {
                if (response.redirected) {
                    window.location.href = response.url; // Redirect to `/set_criteria`
                } else {
                    return response.json();
                }
            })
            .then(data => {
                if (data && data.error) {
                    alert("Error: " + data.error);
                }
            })
            .catch(error => {
                console.error("Error processing essay:", error);
                alert("An error occurred while processing the essay.");
            });
        });
    }
});
