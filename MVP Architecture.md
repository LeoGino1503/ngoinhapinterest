# AI Image-to-Caption Tool (MVP Architecture)

## Overview

This system allows users to simply upload or send an image (via Zalo, web upload, or drag-and-drop), and automatically generates a product-style caption using an AI service.

The goal is to keep the **client experience extremely simple** while building a scalable backend that can be upgraded later.

---

## System Flow

```
Step 1: User (Zalo / Upload / Drag-drop)
        ↓
Step 2: n8n (trigger + orchestration)
        ↓
Step 3: MinIO (image storage)
        ↓
Step 4: AI Service (basic image understanding: colors, object type)
        ↓
Step 5: Redis/PostgreSQL (cache metadata)
        ↓
Step 6: Output:
     - Zalo: caption text
     - Web/API: JSON response
```

---

## Components

### 1. User Input

* **Zalo**: User sends an image to a bot
* **Web Upload**: Simple UI with drag-and-drop
* **API**: Accepts image file upload

---

### 2. n8n (Workflow Orchestration)

Responsible for:

* Receiving image via webhook
* Uploading image to MinIO
* Calling AI service
* Storing metadata in Redis/PostgreSQL
* Returning result to client

---

### 3. MinIO (Object Storage)

* Stores uploaded images
* Generates accessible URLs for AI processing
* Lightweight and easy to deploy via Docker

---

### 4. AI Service (MVP Version)

#### Goal:

Extract basic information from the image:

* Dominant colors (red, blue, yellow, etc.)
* Object type (e.g., carpet, cat, etc.)

#### Suggested MVP Approaches:

**Option A (Recommended - Simple & Fast):**

* Use a lightweight vision API (e.g., Gemini Vision or similar)
* Prompt-based caption generation

**Option B (Local & Cheap):**

* Use a simple model:

  * OpenCV (color detection)
  * Pretrained lightweight classifier (e.g., MobileNet)

#### Output Example:

```json
{
  "object": "cat carpet",
  "colors": ["white", "pink"],
  "confidence": 0.87
}
```

---

### 5. Redis / PostgreSQL

#### Redis (Recommended for MVP):

* Cache generated captions
* Store temporary metadata
* Fast response

#### PostgreSQL (Optional):

* Store history of generated products
* Useful for analytics and future scaling

---

## Output Format

### 1. Zalo Response (Text)

```
Cute cat-shaped carpet
Condition: 90%
Size: 40x55cm
Price: 60,000 VND 🐳
```

---

### 2. Web/API Response (JSON)

```json
{
  "product_name": "Cute cat-shaped carpet",
  "condition": "90%",
  "size": "40x55cm",
  "price": "60000 VND",
  "colors": ["white", "pink"],
  "caption": "Cute cat-shaped carpet\nCondition: 90%\nSize: 40x55cm\nPrice: 60,000 VND 🐳"
}
```

---

## Key Design Principles

* **Minimal UI**: User only needs to upload/send image
* **Automation-first**: n8n handles all orchestration
* **Modular AI**: Easy to upgrade AI model later
* **Scalable storage**: MinIO for images
* **Fast response**: Redis caching

---

## Future Enhancements

* Replace basic AI with advanced multimodal models
* Add Instagram auto-post (via Meta Graph API)
* Add product database & analytics
* Improve caption quality with fine-tuned prompts
* Add multilingual support (Vietnamese/English)

---

## Summary

This MVP focuses on:

* Fast implementation
* Low complexity
* Real-world usability

You can build this system in **1–2 days** and iterate later with more advanced AI models and automation features.
