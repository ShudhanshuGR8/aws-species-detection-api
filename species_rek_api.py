from flask import Flask, request, jsonify
import boto3
from PIL import Image, ImageDraw, ImageFont
import io
import urllib.parse
import json

app = Flask(__name__)

# AWS credentials and configuration
AWS_ACCESS_KEY_ID = 'AKIAXJXXKU5EAU3U2JMJ' #ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY = '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' #SECRET_ACCESS_KEY
AWS_REGION = 'ap-southeast-2' #AWS_REGION
S3_BUCKET_NAME = 'speciesinfostorage' #S3 BUCKET NAME
DYNAMODB_TABLE_NAME = 'SpeciesInformation' #DYNAMODB TABLE NAME
REKOGNITION_MAX_LABELS = 1
POLLY_VOICE_ID = 'Joanna'  # You can change the voice ID as needed

# Initializing AWS clients
s3_client = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name=AWS_REGION)
rekognition_client = boto3.client('rekognition', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name=AWS_REGION)
dynamodb_client = boto3.client('dynamodb', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name=AWS_REGION)
polly_client = boto3.client('polly', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name=AWS_REGION)

# Function to get species information from DynamoDB
def get_species_information_from_dynamodb(species_name):
    response = dynamodb_client.get_item(
        TableName=DYNAMODB_TABLE_NAME,
        Key={'species': {'S': species_name}}
    )
    return response.get('Item', {}).get('information', {}).get('S', '')

# Function to detect labels and annotate the image
def detect_labels_and_annotate(image_bytes):
    detect_objects = rekognition_client.detect_labels(Image={'Bytes': image_bytes})

    image = Image.open(io.BytesIO(image_bytes))
    draw = ImageDraw.Draw(image)

    for label in detect_objects['Labels']:
        print(label["Name"])
        print("Confidence: ", label["Confidence"])

        for instances in label['Instances']:
            if 'BoundingBox' in instances:
                box = instances["BoundingBox"]

                left = image.width * box['Left']
                top = image.height * box['Top']
                width = image.width * box['Width']
                height = image.height * box['Height']

                points = (
                    (left, top),
                    (left + width, top),
                    (left + width, top + height),
                    (left, top + height),
                    (left, top)
                )
                draw.line(points, width=5, fill="#69f5d9")

                shape = [(left - 2, top - 35), (width + 2 + left, top)]
                draw.rectangle(shape, fill="#69f5d9")

                font = ImageFont.truetype("arial.ttf", 30)

                label_with_confidence = f"{label['Name']} {label['Confidence']:.2f}"
                draw.text((left + 170, top - 30), label_with_confidence, font=font, fill='#000000')

                #Amazon Polly to announce the label
                # announce_label_with_polly(label_with_confidence)

    return image

# Function to put annotated image to S3 and read species information from DynamoDB
def process_image_from_s3(bucket_name, key):
    # Downloading image from S3
    print(f"Attempting to download image from S3: {key}")
    response = s3_client.get_object(Bucket=bucket_name, Key=key)
    
    # Add the following print statement to check the response
    print(f"S3 Response: {response}")
    
    image_bytes = response['Body'].read()

    # Detecting labels and annotate the image
    annotated_image = detect_labels_and_annotate(image_bytes)

    # Saving annotated image back to S3
    output_key = 'output-image/' + key
    s3_client.put_object(Body=io.BytesIO(annotated_image.tobytes()).read(),
                         Bucket=bucket_name, Key=output_key)

    # Use Amazon Polly to announce species information
    species_name = key.split('/')[1].split('_')[0]  # Extract species name from the image key
    species_information = get_species_information_from_dynamodb(species_name)
    # announce_species_information_with_polly(species_name, species_information)

    return annotated_image, species_name, species_information, output_key

# Function to use Amazon Polly to announce label
def announce_label_with_polly(label_with_confidence):
    response = polly_client.synthesize_speech(
        Text=label_with_confidence,
        OutputFormat='mp3',
        VoiceId=POLLY_VOICE_ID
    )
    audio_stream = response['AudioStream'].read()
    # play_audio(audio_stream)

# Function to use Amazon Polly to announce species information
def announce_species_information_with_polly(species_name, species_information):
    announcement = f"The detected species is {species_name}. Here is some information about it. {species_information}"
    response = polly_client.synthesize_speech(
        Text=announcement,
        OutputFormat='mp3',
        VoiceId=POLLY_VOICE_ID
    )
    audio_stream = response['AudioStream'].read()
    # play_audio(audio_stream)

# Function to play audio
def play_audio(audio_stream):
    with open('output.mp3', 'wb') as f:
        f.write(audio_stream)
    import subprocess
    subprocess.run(['afplay', 'output.mp3'])  # Assuming macOS, adjust for other systems

# API endpoint for uploading an image
@app.route('/upload', methods=['POST'])
def upload_image():
    # Get the uploaded image from the request
    uploaded_image = request.files['image']
    
    # Save the image to S3 in the input-image folder
    s3_client.upload_fileobj(uploaded_image, S3_BUCKET_NAME, 'input-image/input_1.jpg')

    return jsonify({'message': 'Image uploaded successfully'})

# API endpoint for analyzing the image
@app.route('/analyze', methods=['POST'])
def analyze_image():
    # Get the S3 bucket and key from the request
    s3_bucket = S3_BUCKET_NAME
    s3_key = 'input-image/input_1.jpg'

    # Process the image and get results
    annotated_image_result, species_name_result, species_information_result, output_key_result = process_image_from_s3(s3_bucket, s3_key)

    # Convert the annotated image to bytes and send it in the response
    image_bytes = io.BytesIO(annotated_image_result.tobytes()).read()
    return jsonify({
        'detected_species': species_name_result,
        'species_information': species_information_result,
        'annotated_image': image_bytes.decode('latin1')  # Convert bytes to string for JSON serialization
    })

# API endpoint for announcing species information
@app.route('/announce', methods=['POST'])
def announce_species_information():
    # Get species name and information from the request
    species_name = request.json.get('species_name')
    species_information = request.json.get('species_information')

    # Use Amazon Polly to announce species information
    announce_species_information_with_polly(species_name, species_information)

    return jsonify({'message': 'Species information announced successfully'})

if __name__ == '__main__':
    app.run(debug=True)
