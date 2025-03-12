import os
import re
import g4f
import g4f.Provider
import asyncio
import time
import random
from aiohttp.client_exceptions import ClientResponseError
from g4f.errors import ResponseStatusError
from datetime import timedelta
from flask import Flask, render_template, redirect, url_for, request, session
from markupsafe import Markup

app = Flask(__name__, template_folder="templates")
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

client = g4f.Client()
image_to_text_client = g4f.Client(provider=g4f.Provider.Blackbox)


def image_to_text(image_file):
    try:
        print(f"Received the image: {image_file.filename}")
        images = [[image_file, image_file.filename]]
        response = image_to_text_client.chat.completions.create(
            messages=[{
                "content": (
                    "Extract only the plain text from this image. "
                    "Do not use any special symbols like # or *. "
                    "If there are crossed-out words, ignore them as they are erasures. "
                    "Only include the readable text without any formatting."
                ),
                "role": "user"
            }],
            model="",
            images=images
        )

        if hasattr(response, 'choices') and len(response.choices) > 0:
            content = response.choices[0].message.content
            sanitized_content = content.replace("#", "").replace("*", "").strip()
            print(f"Extracted content: {sanitized_content}")
            return sanitized_content if sanitized_content else "No text could be extracted."
        return "No text could be extracted."
    except Exception as e:
        print(f"Error during image processing: {e}")
        return f"An error occurred during image processing: {str(e)}"

def format_justification(justification):
    justification = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', justification)  # Bold text
    justification = justification.replace("\n", "<br>")  # Line breaks
    justification = re.sub(r'(\d+)\.', r'<br>\1.', justification)  # Preserve numbered lists
    
    return Markup(justification)

def generate_summary(text):
    if len(text.split()) < 20:
        return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita."
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": f"Summarize this text in Filipino:\n\n{text}"}]
        )
        if not response.choices:
            return "No summary could be generated."
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"An error occurred during summarization: {str(e)}"

async def retry_request(func, max_retries=3):
    loop = asyncio.get_event_loop()

    for i in range(max_retries):
        try:
            return await loop.run_in_executor(None, func)
        except Exception as e:  
            if "rate limit" in str(e).lower():  
                wait_time = (2 ** i) + random.uniform(0, 1)
                print(f"Rate limit hit, retrying in {wait_time:.2f} seconds...")
                await asyncio.sleep(wait_time)
            else:
                raise e  
    raise Exception("Max retries reached")

async def grade_essay(essay_text, context_text):
    if len(essay_text.split()) < 20:
        return "Error: Ang input na teksto ay dapat magkaroon ng hindi bababa sa 20 salita."

    criteria = session.get('criteria', [])
    if not criteria:
        return "No criteria set for grading."
    
    total_points_possible = session.get('total_points_possible', 0)
    if total_points_possible == 0:
        return "No valid criteria to grade the essay."
    
    total_points_received = 0
    grades_per_criterion = []
    
    grade_pattern = re.compile(r"Grade:\s*(\d+(\.\d+)?)\/(\d+)")
    justification_pattern = re.compile(r"Justification:\s*(.*)", re.DOTALL)

    for criterion in criteria:
        truncated_essay = essay_text[:1000]

        try:
            response = await retry_request(lambda: g4f.ChatCompletion.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Grade the following student work based on the criterion '{criterion['name']}' out of {criterion['points_possible']} points.\n\n"
                        f"Context from teacher: {context_text}\n\n"
                        f"Essay to grade: {truncated_essay}\n\n"
                        f"Grade: [numeric value]/{criterion['points_possible']}\n"
                        "Justification: [3-sentence detailed justification including examples]"
                    )
                }]
            ))

            if not isinstance(response, dict) or 'choices' not in response:
                return f"Error processing AI response: {response}"

            raw_grade = response['choices'][0]['message']['content'].strip()
            
            grade_match = grade_pattern.search(raw_grade)
            points_received = float(grade_match.group(1)) if grade_match else 0

            justification_match = justification_pattern.search(raw_grade)
            justification = justification_match.group(1).strip() if justification_match else "No justification provided."

        except Exception as e:
            points_received = 0
            justification = f"Error processing AI response: {str(e)}"

        total_points_received += points_received
        grades_per_criterion.append(f"Criterion: {criterion['name']} - Grade: {points_received}/{criterion['points_possible']} - Justification: {justification}")

    final_grade = f"{total_points_received}/{total_points_possible}"
    result_summary = "\n".join(grades_per_criterion)

    return f"Final Grade: {final_grade}\n\n{result_summary}"

@app.route('/')
def home():
    return redirect(url_for('front_page'))

@app.route('/front')
def front_page():
    return render_template('front_page.html')

@app.route('/scan', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        student_name = request.form.get('student_name', '').strip()
        session['student_name'] = student_name

        context = request.form.get('context', '').strip()
        session['context_text'] = context
        
        image = request.files.get('image')
        if image:
            essay = image_to_text(image)
            if "Error" in essay:
                return render_template('index.html', error=essay, context=context)
        else:
            essay = request.form.get('essay', '')

        session['original_text'] = essay
        
        return redirect(url_for('set_criteria'))

    return render_template('index.html', context=session.get('context_text', ''))

@app.route('/set_criteria', methods=['GET', 'POST'])
def set_criteria():
    if request.method == 'POST':
        new_criterion = {
            'name': request.form['criterion_name'],
            'points_possible': float(request.form['points_possible'])
        }

        if 'criteria' not in session:
            session['criteria'] = []
        
        session['criteria'].append(new_criterion)
        session.modified = True

        session['total_points_possible'] = sum(criterion['points_possible'] for criterion in session['criteria'])

        return redirect(url_for('set_criteria'))

    return render_template('set_criteria.html', criteria=session.get('criteria', []))

@app.route('/process_essay', methods=['POST'])
def process_essay():
    summary_result = generate_summary(session.get('original_text', ''))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    grade_result = loop.run_until_complete(grade_essay(session.get('original_text', ''), session.get('context_text', '')))
    loop.close()

    return render_template('results.html', summary=summary_result, grade=grade_result)

@app.route('/clear_session', methods=['POST'])
def clear_session():
    session.clear()
    return redirect(url_for('set_criteria'))

if __name__ == '__main__':
    app.run(debug=True)
