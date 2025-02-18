# 🏡 Real Estate Management System with Web Scraping from Divar

## 📌 About the Project

This project is a **Real Estate Management System** backend that enables users to **add, edit, and manage properties** with all necessary features such as **area, rooms, parking, elevator, heating system, yard, and more**.

Additionally, it provides **web scraping capabilities from the Divar website**, allowing the system to **import and integrate real estate listings from Divar into the database**.

This project is built using **Django REST Framework (DRF) and MongoDB**, providing a robust, scalable, and efficient solution for real estate management.

---

## ✨ Key Features

### 🔹 **Real Estate Management**
- Add, update, and delete properties in pure pymongo for highest performance.
- Update, delete any nested complex attributes of the property.
- Property images, comments, category and author all supports.
- Auto generate queries to run in mongo.

### 🔹 **Web Scraping from Divar**
- Crawl real estate listings from [Divar](https://divar.ir).
- Extract property details including title, price, location, images, and descriptions.
- Store the extracted data in MongoDB.
- Control the numbers of property and location for more accurate crawling.

### 🔹 **Blogging System**
- **Blog posts** supports.
- **Rich text editor** support for formatted content.
- **Commenting system** for user engagement.
- **Categorization and tagging** for better organization.
- ...

### 🔹 **Hybrid Database Architecture**
- **MongoDB for Real Estate Listings**:  
  - Main project implemented by Mongo.
  - Schema flexibility for property attributes.
- **PostgreSQL for User & Category**:  
  - **Structured relational data storage** for user authentication and categories.
  - **Improved integrity for authentication and categorization**.

### 🔹 **API Integration & Mobile Compatibility**
- RESTful API for third-party integrations.
- manage CORS and return proper response errors.


---

## 🛠️ Tech Stack

| **Technology**   | **Usage** |
|------------------|-----------|
| Django & DRF    | Backend & API development |
| MongoDB         | NoSQL database for property storage |
| Selenium        | Web scraping from Divar |
| Pymongo         | MongoDB database management |
| JWT Auth        | Secure authentication |
| Docker          | Containerized deployment |

---

## 🚀 How to Run the Project

## 1️⃣ **Clone the Repository**
```bash
git clone https://github.com/your-username/real-estate-management.git
cd real-estate-management
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Add .env in the 'Property-Management folder with this structure:  
```
SECRET_KEY=-l(24ils3ph2mp0%cguxdq!i%8cfjfldw*1ugu+a@9wk^2x^-e  # replace your project secret key  
POSTGRES_MY_HOST=127.0.0.1
POSTGRES_DBNAME=
POSTGRES_USERNAME=
POSTGRES_USERPASS=
MONGO_HOST=127.0.0.1
MONGO_DBNAME=
MONGO_SOURCE=admin
MONGO_USERNAME=
MONGO_USERPASS=
MONGO_ADMINUSER=
```

Create postgres and mongo db with that information.  

**Note**: SECRET_KEY is django settings/SECRET_KEY. provided default value works fine but recommended to replace with your project SECRET_KEY.   
    
***
## 2️⃣ **Docker**

To set up and run this project using Docker, follow these steps:

1. Clone this repository:
   ```sh
   git clone https://github.com/ahmadekhalili/docker-Property
   cd docker-Property
   ```
2. Create and run DBs (Mongo and Postgres)
   ```sh

   ```
3. Run the docker:
   ```sh
   docker compose up -d
   ```

now site accessible in 0.0.0.0:8000.
