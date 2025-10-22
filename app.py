from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
import pandas as pd
import praw
from datetime import datetime
import os
import threading
from io import BytesIO

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

# ---------------- Reddit API setup ----------------
REDDIT_CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID')
REDDIT_SECRET = os.environ.get('REDDIT_SECRET')
REDDIT_USER_AGENT = os.environ.get('REDDIT_USER_AGENT', 'RedditKeywordSearchBot/1.0')

# Initialize Reddit client only if credentials are available
if REDDIT_CLIENT_ID and REDDIT_SECRET:
    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_SECRET,
            user_agent=REDDIT_USER_AGENT
        )
        # Test the connection
        reddit.user.me()  # This will raise an exception if credentials are invalid
        print("Reddit API connection successful")
    except Exception as e:
        print(f"Reddit API connection failed: {e}")
        reddit = None
else:
    print("Reddit API credentials not found")
    reddit = None

# Global variable to store search progress
search_progress = {
    'current': 0,
    'total': 0,
    'message': '',
    'is_running': False,
    'results': None,
    'error': None,
    'search_id': None
}

def search_reddit(keywords, search_id):
    global search_progress
    results = []
    total = len(keywords)
    
    # Check if Reddit client is properly initialized
    if reddit is None:
        search_progress['error'] = "Reddit API not configured properly. Please check your environment variables."
        search_progress['is_running'] = False
        return None
    
    search_progress['total'] = total
    search_progress['current'] = 0
    search_progress['is_running'] = True
    search_progress['error'] = None
    search_progress['search_id'] = search_id
    search_progress['results'] = None
    
    try:
        for i, keyword in enumerate(keywords, start=1):
            search_progress['current'] = i
            search_progress['message'] = f"Searching for: {keyword}"
            
            try:
                # Add timeout for Vercel's serverless environment
                for submission in reddit.subreddit("all").search(keyword, sort="top", limit=5):  # Reduced limit for Vercel
                    results.append({
                        "Keyword": keyword,
                        "Title": submission.title,
                        "Subreddit": submission.subreddit.display_name,
                        "Score": submission.score,
                        "Comments": submission.num_comments,
                        "URL": submission.url,
                        "Created_UTC": datetime.fromtimestamp(submission.created_utc).strftime('%Y-%m-%d %H:%M:%S')
                    })
            except Exception as e:
                print(f"Error while searching for '{keyword}': {e}")
                continue
        
        search_progress['results'] = results
        search_progress['is_running'] = False
        return results
        
    except Exception as e:
        search_progress['error'] = str(e)
        search_progress['is_running'] = False
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global search_progress
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file selected'})
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'error': 'Please upload an Excel file (.xlsx or .xls)'})
    
    try:
        # Check file size (limit to 5MB for Vercel)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset seek position
        
        if file_size > 5 * 1024 * 1024:  # 5MB limit for Vercel
            return jsonify({'success': False, 'error': 'File size too large. Maximum 5MB allowed.'})
        
        df = pd.read_excel(file)
        if "Keyword" not in df.columns:
            return jsonify({'success': False, 'error': "Excel file must have a 'Keyword' column"})
        
        keywords = df["Keyword"].dropna().tolist()
        
        if not keywords:
            return jsonify({'success': False, 'error': "No keywords found in the Excel file"})
        
        # Limit the number of keywords for Vercel (serverless timeout)
        if len(keywords) > 20:
            return jsonify({'success': False, 'error': "Too many keywords. Maximum 20 keywords allowed for Vercel deployment."})
        
        # Generate a unique search ID
        search_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Start search in background thread
        thread = threading.Thread(target=search_reddit, args=(keywords, search_id))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'search_id': search_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error reading file: {str(e)}'})

@app.route('/progress_data')
def progress_data():
    global search_progress
    return jsonify({
        'current': search_progress['current'],
        'total': search_progress['total'],
        'message': search_progress['message'],
        'is_running': search_progress['is_running'],
        'has_results': search_progress['results'] is not None,
        'error': search_progress['error'],
        'search_id': search_progress['search_id']
    })

@app.route('/results')
def show_results():
    global search_progress
    
    if search_progress['results'] is None:
        flash('No results available. Please run a search first.', 'error')
        return redirect('/')
    
    results = search_progress['results']
    return render_template('results.html', results=results, total_results=len(results))

@app.route('/download')
def download_results():
    global search_progress
    
    if search_progress['results'] is None:
        flash('No results available to download', 'error')
        return redirect('/')
    
    # Create Excel file in memory
    output = BytesIO()
    df = pd.DataFrame(search_progress['results'])
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Reddit_Results')
    
    output.seek(0)
    filename = f"reddit_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/reset')
def reset():
    global search_progress
    search_progress = {
        'current': 0,
        'total': 0,
        'message': '',
        'is_running': False,
        'results': None,
        'error': None,
        'search_id': None
    }
    return redirect('/')

# Vercel requires this
if __name__ == '__main__':
    app.run(debug=True)