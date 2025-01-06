
import openai
from flask import Flask, request, jsonify, render_template
from youtube_auth import authenticate_youtube_api
from youtube_comments import fetch_comments_with_replies, post_reply, generate_reply
from youtube_utils import fetch_all_video_ids_from_channel  # Assuming this exists
import time

# Set API keys directly
openai.api_key = "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"  # Replace with your actual OpenAI API key
YOUTUBE_API_KEY = "AIzaSyA8qclHhZNDRlaJ2ZBUmy-3ocO638rhXFE"  # Replace with your actual YouTube API key

# Check for missing API keys
if not openai.api_key or not YOUTUBE_API_KEY:
    raise EnvironmentError("Missing API keys. Ensure both OPENAI_API_KEY and YOUTUBE_API_KEY are set.")

# Global set to store processed comment IDs
processed_comment_ids = set()

# Initialize Flask App
app = Flask(__name__)

@app.route("/")
def home():
    try:
        return render_template("index.html")
    except Exception as e:
        return jsonify({"error": f"Error rendering template: {e}"}), 500
        

@app.route('/favicon.ico')
def favicon():
    """
    Handle favicon requests to avoid unnecessary 404s.
    """
    return "", 204

# In-memory storage for replies awaiting approval
pending_replies = []

@app.route('/callback')
def oauth2callback():
    # Get the authorization code from the query string
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization code not provided"}), 400

    # Exchange the authorization code for access and refresh tokens
    token_url = 'https://oauth2.googleapis.com/token'
    payload = {
        'code': code,
        'client_id': '83454611538-dgdso66evbooi31ovv5hj9pdj0mi01l8.apps.googleusercontent.com',  # Replace with your actual Client ID
        'client_secret': 'YOUR_CLIENT_SECRET',  # Replace with your actual Client Secret
        'redirect_uri': 'http://localhost:8080/callback',  # Must match redirect URI in frontend
        'grant_type': 'authorization_code'
    }

    try:
        response = requests.post(token_url, data=payload)
        response.raise_for_status()
        token_data = response.json()

        # Return or process tokens as needed
        return jsonify(token_data)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 400



@app.route('/fetch-channel-comments', methods=['GET'])
def fetch_channel_comments():
    channel_id = request.args.get('channelId')
    if not channel_id:
        return jsonify({"error": "Channel ID is required"}), 400

    try:
        # Fetch video IDs and their comments
        video_ids = fetch_all_video_ids_from_channel(channel_id)
        all_comments = []
        for video_id in video_ids:
            comments = fetch_comments_with_replies(video_id)
            all_comments.extend(comments)

        return jsonify({"pending_replies": all_comments})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/process', methods=['POST'])
def process_youtube_comments():
    """
    Fetch comments (including subcomments), filter out comments already answered by the bot,
    heart the comments, generate replies, and prepare them for manual approval.
    """
    try:
        global pending_replies  # List to store replies awaiting approval
        pending_replies = []  # Reset pending replies for each new video processing

        # Parse incoming JSON payload
        data = request.get_json()
        video_url = data.get("url")
        role = data.get("role", "community")  # Default role is community member

        if not video_url:
            return jsonify({"error": "YouTube video URL is required"}), 400

        # Extract the video ID from the URL
        video_id = extract_video_id(video_url)
        if not video_id:
            return jsonify({"error": "Invalid YouTube video URL"}), 400

        # Authenticate YouTube API
        youtube = authenticate_youtube_api()

        # Fetch the bot's own channel ID
        channel_response = youtube.channels().list(part="id", mine=True).execute()
        bot_channel_id = channel_response["items"][0]["id"]
        print(f"Bot's channel ID: {bot_channel_id}")

        comments = []


        if video_url:
            # Process for a specific video
            video_id = extract_video_id(video_url)
            if not video_id:
                return jsonify({"error": "Invalid YouTube video URL"}), 400

            comments = fetch_comments_with_replies(youtube, video_id)

        elif channel_id:
            # Process for all videos in a channel
            video_ids = fetch_all_video_ids_from_channel(youtube, channel_id)
            for video_id in video_ids:
                video_comments = fetch_comments_with_replies(youtube, video_id)
                comments.extend(video_comments)

        if not comments:
            print("No comments found.")
            return jsonify({"error": "No comments found."}), 404

        # Iterate through fetched comments
        for comment in comments:
            try:
                # Validate comment structure
                comment_id = comment["commentId"]
                author_channel_id = comment["authorChannelId"]
                comment_text = comment["text"]
                already_replied_by_bot = comment["alreadyRepliedByBot"]

                # Skip comments made by the bot itself if role is "owner"
                if role == "owner" and author_channel_id == bot_channel_id:
                    print(f"Skipping bot's own comment: {comment_text}")
                    continue

                # Skip comments already replied to by the bot
                if already_replied_by_bot:
                    print(f"Skipping already-replied comment: {comment_text}")
                    continue

                # Heart the comment (if the bot is the channel owner)
                if role == "owner":
                    try:
                        youtube.comments().setModerationStatus(
                            id=comment_id,
                            moderationStatus="published",
                            banAuthor=False
                        ).execute()
                        print(f"Hearted comment: {comment_text}")
                    except Exception as e:
                        print(f"Failed to heart comment: {comment_text}. Error: {e}")

                # Generate a reply using OpenAI
                reply = generate_reply(
                    comment_text, 
                    role, 
                    data.get("mood", "casual"), 
                    data.get("appendSignature", False)  # Pass appendSignature flag
                )

                # Add the comment and reply to pending replies for manual approval
                pending_replies.append({
                    "commentId": comment_id,
                    "commentText": comment_text,
                    "generatedReply": reply,
                    "approvedReply": None,  # Placeholder for manual approval
                    "author": author_channel_id
                })

            except Exception as e:
                print(f"Error processing comment: {comment}. Error: {e}")

        # Return prepared replies for manual approval
        return jsonify({
            "message": "Replies prepared for approval.",
            "pending_replies": pending_replies
        })
    except Exception as e:
        print(f"Error in /process endpoint: {e}")
        return jsonify({"error": str(e)}), 500


def fetch_comments_with_replies(youtube, video_id):
    """
    Fetch comments and their replies from the YouTube video and mark those already replied by the bot.
    """
    try:
        comments = []
        request = youtube.commentThreads().list(
            part="snippet,replies",
            videoId=video_id,
            maxResults=100,
            moderationStatus="published"
        )

        while request:
            response = request.execute()
            for item in response.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]

                # Check if the bot has already replied to this comment
                already_replied_by_bot = False
                if "replies" in item:
                    for reply in item["replies"]["comments"]:
                        reply_author_id = reply["snippet"]["authorChannelId"]["value"]
                        if reply_author_id == snippet["authorChannelId"]:
                            already_replied_by_bot = True
                            break

                comments.append({
                    "commentId": item["id"],
                    "text": snippet["textDisplay"],
                    "authorChannelId": snippet["authorChannelId"]["value"],
                    "alreadyRepliedByBot": already_replied_by_bot
                })

            request = youtube.commentThreads().list_next(request, response)

        return comments
    except Exception as e:
        print(f"Error fetching comments with replies: {e}")
        return []



@app.route('/api/approve', methods=['POST'])
def approve_replies():
    """
    Process approved replies and post them to YouTube.
    """
    try:
        print("✅ Received request at /approve")

        # Parse the incoming JSON payload
        data = request.get_json(silent=True)
        if not data:
            print("❌ Error: No JSON payload received.")
            return jsonify({"error": "Invalid JSON payload."}), 400

        # Extract 'approvedReplies' from the JSON payload
        approved_replies = data.get('approvedReplies', [])
        if not approved_replies:
            print("❌ Error: No approved replies provided.")
            return jsonify({"error": "No approved replies provided."}), 400

        youtube = authenticate_youtube_api()
        approved_count = 0

        # Process approved replies
        for reply in approved_replies:
            comment_id = reply.get('commentId')
            approved_reply = reply.get('approvedReply')

            if not comment_id or not approved_reply:
                print(f"❌ Skipping invalid reply: {reply}")
                continue

            try:
                print(f"✅ Posting reply: Comment ID = {comment_id}, Reply = {approved_reply}")
                post_reply(youtube, comment_id, approved_reply)
                approved_count += 1
            except Exception as e:
                print(f"❌ Error posting reply for Comment ID {comment_id}: {e}")

        print(f"✅ Successfully posted {approved_count} replies.")
        return jsonify({"message": f"{approved_count} replies posted successfully."}), 200
    except Exception as e:
        print(f"❌ Unexpected server error: {e}")
        return jsonify({"error": str(e)}), 500



def extract_video_id(url):
    """
    Extracts the video ID from a YouTube URL.
    """
    try:
        if "v=" in url:
            return url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            return url.split("youtu.be/")[1].split("?")[0]
        return None
    except Exception:
        return None





from openai import Client  # Import the updated Client
from flask import Flask  # Assuming Flask is used
import os

# Initialize OpenAI Client with API key
client = Client(api_key="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")  # Replace with your actual key

def generate_reply(comment_text, role, mood="casual", append_signature=False):
    """
    Generate a concise and engaging reply to a YouTube comment based on the user's role and mood.

    Parameters:
    - comment_text (str): The YouTube comment text.
    - role (str): The role of the responder ("owner" or "community").
    - mood (str): The mood of the response ("casual", "funny", "professional").
    - append_signature (bool): Whether to append 'Cheers, Abhi' as a signature.

    Returns:
    - str: The generated reply.
    """
    try:
        # Role-specific instructions
        role_instructions = {
            "owner": (
                "You are Abhi Duggal, the owner of the YouTube channel. Respond warmly, professionally, and concisely, "
                "showing gratitude for the commenter's engagement. Keep responses short and end with a question when appropriate. "
                "Sign off with 'Cheers, Abhi' if applicable."
            ),
            "community": (
                "You are responding on behalf of the community for the YouTube channel. Your goal is to foster meaningful, "
                "positive conversations. Highlight shared experiences, keep responses brief, and encourage engagement by "
                "Only ask questions if they are crucial to creating a meaningful conversation or engaging with the audience in a thoughtful way. "
                "Keep responses brief and express gratitude, avoiding phrases that could imply ownership  use I'm glad you liked it or Thanks for the kind words, rather than taking credit"
            ),
        }


        # Mood-specific instructions
        mood_instructions = {
            "funny": "Your tone should be lighthearted and humorous, with playful remarks or jokes.",
            "casual": "Your tone should be friendly, casual, and conversational.",
            "professional": "Your tone should be formal, respectful, and concise.",
        }

        # Validate role and mood
        if role not in role_instructions:
            raise ValueError(f"Invalid role: {role}. Expected 'owner' or 'community'.")
        if mood not in mood_instructions:
            raise ValueError(f"Invalid mood: {mood}. Expected 'casual', 'funny', or 'professional'.")

        # Combine role and mood instructions
        role_text = role_instructions[role]
        mood_text = mood_instructions[mood]

        # OpenAI API Call using updated client structure
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": f"{role_text} {mood_text} Your replies should feel authentic, concise, and context-aware."
                },
                {
                    "role": "user",
                    "content": f"Comment: {comment_text}\nReply accordingly."
                }
            ],
            max_tokens=150,
            temperature=0.7
        )

        # Extract and process the reply
        reply = response.choices[0].message.content.strip()

        # Conditionally append the signature
        if role == "owner" and append_signature:
            reply += "\n\nCheers,\nAbhi"

        return reply

    except Exception as e:
        print(f"Error generating reply for role {role} and mood {mood}: {e}")
        return "We appreciate your comment and support!"



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
