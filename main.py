import sqlite3
import sys
import getpass
import re
from datetime import datetime
from datetime import date


# Function to establish a connection to the SQLite database
def connect_to_db(db_name):
    try:
        return sqlite3.connect(db_name)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        sys.exit(1)

# Function to validate email format
def is_valid_email(email):
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email) is not None

# Function to validate birth year as a number
def is_valid_year(year):
    try:
        int_year = int(year)
        return 1900 <= int_year <= 2024  # Assuming valid birth years range
    except ValueError:
        return False

# Function to check user credentials (modified to include error check before password prompt)
def login(conn, email):
    if not is_valid_email(email):
        print("Invalid email format.")
        return None
    cursor = conn.cursor()
    # Convert input email to lowercase for comparison
    email_lower = email.lower()
    cursor.execute("SELECT * FROM members WHERE lower(email) = ?", (email_lower,))
    user = cursor.fetchone()
    return user

# Function to register a new user with email uniqueness check (modified to check before password prompt)
def signup(conn, email):
    if not is_valid_email(email):
        print("Invalid email format.")
        return False
    if email.strip() == '':
        print("Email cannot be empty.")
        return False
    cursor = conn.cursor()
    # Check for existing email in a case-insensitive manner but store the email as entered
    email_lower = email.lower()
    cursor.execute("SELECT * FROM members WHERE lower(email) = lower(?)", (email_lower,))
    if cursor.fetchone():
        print("Email already exists.")
        return False
    passwd = getpass.getpass("Enter your password: ").strip()
    if passwd == '':
        print("Password cannot be empty.")
        return False
    name = input("Enter your name: ").strip()
    if name == '':
        print("Name cannot be empty.")
        return False
    byear = input("Enter your birth year (optional): ").strip()
    if byear and not is_valid_year(byear):
        print("Invalid birth year.")
        return False
    faculty = input("Enter your faculty name (optional): ").strip()
    # Store the email exactly as entered
    cursor.execute("INSERT INTO members (email, passwd, name, byear, faculty) VALUES (?, ?, ?, ?, ?)",
                   (email, passwd, name, byear if byear else None, faculty if faculty else None))
    conn.commit()
    return True


def view_member_profile(conn, member_email):
    cursor = conn.cursor()
    # Fetch and display personal information
    cursor.execute("SELECT name, email, byear FROM members WHERE email = ?", (member_email,))
    personal_info = cursor.fetchone()
    print(f"\nPersonal Information:\nName: {personal_info[0]}\nEmail: {personal_info[1]}\nBirth Year: {personal_info[2]}")

    # Fetch and display borrowing information
    cursor.execute("""
    SELECT COUNT(bid) FROM borrowings WHERE member = ? AND end_date IS NOT NULL
    """, (member_email,))
    previous_borrowings = cursor.fetchone()[0]
    current_date = date.today()

    cursor.execute(f"""
    SELECT COUNT(bid), 
           SUM(CASE WHEN julianday('{current_date}') - julianday(start_date) > 20 THEN 1 ELSE 0 END)
    FROM borrowings WHERE member = ? AND end_date IS NULL
    """, (member_email,))
    current_borrowings, overdue_borrowings = cursor.fetchone()

    print("\nBorrowing Information:")
    print(f"Previous Borrowings: {previous_borrowings}")
    print(f"Current Borrowings: {current_borrowings}")
    print(f"Overdue Borrowings: {overdue_borrowings}")

  # Fetch and display penalty information
    cursor.execute("""
    SELECT COUNT(pid) AS num_unpaid_penalties, 
           SUM(amount - IFNULL(paid_amount, 0)) AS total_unpaid_debt
    FROM penalties 
    JOIN borrowings ON penalties.bid = borrowings.bid 
    WHERE borrowings.member = ? AND amount > IFNULL(paid_amount, 0)
    """, (member_email,))
    penalty_info = cursor.fetchone()

    num_unpaid_penalties = penalty_info[0] if penalty_info[0] is not None else 0
    total_unpaid_debt = penalty_info[1] if penalty_info[1] is not None else 0.0

    print("\nPenalty Information:")
    print(f"Number of Unpaid Penalties: {num_unpaid_penalties}")
    print(f"Total Debt Amount on Unpaid Penalties: ${total_unpaid_debt:.2f}")



def pay_penalty(conn, member_email):
    cursor = conn.cursor()
    # Fetch unpaid penalties for the user
    cursor.execute("""
        SELECT p.pid, p.amount, p.paid_amount, (p.amount - IFNULL(p.paid_amount, 0)) as due
        FROM penalties p
        JOIN borrowings b ON p.bid = b.bid
        WHERE b.member = ? AND p.amount > IFNULL(p.paid_amount, 0)
    """, (member_email,))
    penalties = cursor.fetchall()

    if not penalties:
        print("No unpaid penalties found.")
        return

    print("Unpaid Penalties:")
    for pid, amount, paid_amount, due in penalties:
        # Display '0' if paid_amount is None for user clarity, while retaining NULL in database logic
        display_paid_amount = '0' if paid_amount is None else paid_amount
        print(f"Penalty ID: {pid}, Total Amount: ${amount}, Paid: ${display_paid_amount}, Due: ${due}")

    pid_to_pay = input("Enter the Penalty ID to pay or 'exit' to cancel: ")
    if pid_to_pay.lower() == 'exit':
        return

    selected_penalty = next((p for p in penalties if str(p[0]) == pid_to_pay), None)
    if not selected_penalty:
        print("Invalid Penalty ID.")
        return

    pay_amount = input(f"Enter amount to pay towards Penalty ID {pid_to_pay} (Due: ${selected_penalty[3]}): ")
    try:
        pay_amount = float(pay_amount)
        if pay_amount <= 0:
            print("Payment amount must be positive.")
            return
    except ValueError:
        print("Please enter a valid number for the payment amount.")
        return

    # Update the penalty with the paid amount only if a payment is being made
    if selected_penalty[2] is not None:  # If there was already some payment
        new_paid_amount = selected_penalty[2] + pay_amount
    else:
        new_paid_amount = pay_amount if pay_amount > 0 else None  # Set to None if no payment was made yet

    cursor.execute("UPDATE penalties SET paid_amount = ? WHERE pid = ?", (new_paid_amount, pid_to_pay))
    conn.commit()

    print(f"Payment of ${pay_amount} successful towards Penalty ID: {pid_to_pay}. Remaining Due: ${selected_penalty[3] - pay_amount}")

    if selected_penalty[3] - pay_amount == 0:
        print("The penalty has been fully paid off.")
    else:
        print(f"Remaining balance for Penalty ID {pid_to_pay}: ${selected_penalty[3] - pay_amount}")

def search_books(conn, member_email):
    page = 0  # Start with the first page
    keyword = input("Enter a keyword to search for books (title or author): ").strip()  # Get the keyword once before the loop
    cursor = conn.cursor()
    cursor.execute("""SELECT COUNT(*) FROM books WHERE title LIKE '%' || ? || '%' OR author LIKE '%' || ? || '%'""",(keyword, keyword))
    num = cursor.fetchall()
    while True:  # Loop to allow pagination
        cursor = conn.cursor()
        offset = page * 5  # Calculate offset for pagination
        cursor.execute("""
            SELECT book_id, title, author, pyear,
                   COALESCE((SELECT AVG(rating) FROM reviews WHERE book_id = books.book_id), 'No ratings') AS average_rating,
                   CASE 
                       WHEN EXISTS (SELECT 1 FROM borrowings WHERE book_id = books.book_id AND end_date IS NULL) 
                       THEN 'Borrowed' 
                       ELSE 'Available' 
                   END AS availability
            FROM books
            WHERE title LIKE '%' || ? || '%' OR author LIKE '%' || ? || '%'
            ORDER BY
                   CASE
                       WHEN title LIKE '%' || ? || '%' THEN 0
                       ELSE 1
                   END,
                   CASE
                       WHEN title LIKE '%' || ? || '%' THEN title
                       ELSE author
                   END
            LIMIT 5 OFFSET ?
        """, (keyword, keyword, keyword, keyword, offset))
        books = cursor.fetchall()

        if not books and page == 0:
            print("No books found for your search.")
            return  # Exit the search function if no books found at all

        for book in books:
            print(f"Book ID: {book[0]}, Title: {book[1]}, Author: {book[2]}, Year: {book[3]}, Avg. Rating: {book[4]}, Status: {book[5]}")

        if len(books) < 5 or ((page+1)*5 == num):
            print("No more pages to display.")  # Less than 5 books in the last fetched page indicates no more results
            next_action = input("Enter 'b' to borrow a book, or any other key to exit: ").strip().lower()
        else:
            next_action = input("Enter 'b' to borrow a book, 'n' to see next page, or any other key to exit: ").strip().lower()
        
        if next_action == 'b':
            while True:  # This while loop allows borrowing multiple books
                book_id_to_borrow = input("Enter the Book ID of the book you want to borrow, or 'm' to return to the main menu: ").strip()
                if book_id_to_borrow.lower() == 'm':  # Return to main menu
                    return
                if book_id_to_borrow.isdigit():
                    borrow_book(conn, member_email, book_id_to_borrow)
                else:
                    print("Invalid Book ID. Please try again.")
        elif next_action == 'n' and len(books) == 5:
            page += 1  # Move to the next page if 'n' is chosen and the last page had full results
        else:
            break  # Exit the loop if any other key is pressed or there are no more results to show


# The borrow_book function remains the same as you provided, no changes needed
def borrow_book(conn, member_email, book_id_to_borrow):
    cursor = conn.cursor()

    # Check if the user has already borrowed the same book and hasn't returned it yet
    cursor.execute("""
    SELECT book_id FROM borrowings
    WHERE member = ? AND book_id = ? AND end_date IS NULL
    """, (member_email, book_id_to_borrow))
    already_borrowed = cursor.fetchone()
    
    if already_borrowed:
        print("You have already borrowed this book and have not returned it yet.")
        return

    # Check if the book is available for borrowing (i.e., not currently borrowed by another user)
    cursor.execute("""
    SELECT book_id FROM books
    WHERE book_id = ? AND book_id NOT IN (SELECT book_id FROM borrowings WHERE end_date IS NULL)
    """, (book_id_to_borrow,))
    available_book = cursor.fetchone()
    
    if not available_book:
        print("This book is not available for borrowing at the moment as it is being borrowed by another user.")
        return

    # Insert a new borrowing record
    current_date = date.today()
    cursor.execute(f"INSERT INTO borrowings (member, book_id, start_date) VALUES (?, ?, date('{current_date}'))", (member_email, book_id_to_borrow))
    conn.commit()
    print("Book borrowed successfully.")



def return_book(conn, member_email):
    cursor = conn.cursor()
    current_date = date.today()
    cursor.execute(f"""
        SELECT borrowings.bid, borrowings.book_id, books.title, 
               DATE(borrowings.start_date) AS start_date, 
               DATE(borrowings.start_date, '+20 days') AS return_deadline,
               julianday(date('{current_date}')) - julianday(borrowings.start_date) AS days_borrowed
        FROM borrowings
        JOIN books ON borrowings.book_id = books.book_id
        WHERE borrowings.member = ? AND borrowings.end_date IS NULL
    """, (member_email,))
    borrowings = cursor.fetchall()

    if not borrowings:
        print("You do not have any current borrowings.")
        return

    print("Your current borrowings:")
    for borrowing in borrowings:
        # Ensure days_borrowed is calculated correctly for books not yet returned
        days_borrowed = round(float(borrowing[5]))  # Ensure days_borrowed is a rounded integer
        print(f"Borrowing ID: {borrowing[0]}, Book ID: {borrowing[1]}, Title: {borrowing[2]}, Start Date: {borrowing[3]}, Return Deadline: {borrowing[4]}, Days Borrowed: {days_borrowed}")

    # Continuation of function...


    bid_to_return = input("Enter the Borrowing ID of the book to return: ")
    selected_borrowing = next((b for b in borrowings if str(b[0]) == bid_to_return), None)
    
    if selected_borrowing:
        current_date = date.today()
        cursor.execute("UPDATE borrowings SET end_date = date(?) WHERE bid = ?", (current_date, bid_to_return))
        conn.commit()
        print("Book returned successfully.")

        overdue_days = max(0, round(float(selected_borrowing[5])) - 20)
        if overdue_days > 0:
            penalty = overdue_days * 1  # Calculate the penalty based on overdue days
            # Insert penalty with paid_amount set to NULL
            cursor.execute("INSERT INTO penalties (bid, amount, paid_amount) VALUES (?, ?, NULL)", (bid_to_return, penalty))
            conn.commit()
            print(f"Penalty of ${penalty} applied for {overdue_days} days overdue.")
        review_prompt = input("Would you like to leave a review for this book? (yes/no): ")
        if review_prompt.lower() == 'yes':
            while True:  # Keep asking until a valid rating is provided
                rating = input("Provide your rating (1-5): ")
                if rating.isdigit() and int(rating) in [1, 2, 3, 4, 5]:
                    break
                else:
                    print("Invalid rating. Please enter a number between 1 and 5.")
        
            review_text = input("Write your review: ")
            review_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                INSERT INTO reviews (book_id, member, rating, rtext, rdate)
                VALUES (?, ?, ?, ?, ?)
            """, (selected_borrowing[1], member_email, int(rating), review_text, review_date))
            conn.commit()
            print("Thank you for your review!")
    else:
        print("Invalid Borrowing ID.")



def main_menu(conn, user_email):
    while True:
        print("\nMain Menu")
        print("1. View Member Profile")
        print("2. View and Pay Penalty")
        print("3. Search for Books")  # Borrowing integrated here
        print("4. Return a Book")
        print("5. Log out")
        choice = input("Enter your choice: ")
        
        if choice == '1':
            view_member_profile(conn, user_email)
        elif choice == '2':
            pay_penalty(conn, user_email)
        elif choice == '3':
            search_books(conn, user_email)  # Pass user_email for potential borrowing
        elif choice == '4':
            return_book(conn, user_email)
        elif choice == '5':
            break  # Log out
        else:
            print("Invalid choice, please try again.")


def main(db_name):
    conn = connect_to_db(db_name)
    while True:
        print("\nWelcome to the Library Management System")
        print("Type '1' or 'login' to Login")
        print("Type '2' or 'signup' to Sign up")
        print("Type '3' or 'exit' to Exit")
        main_choice = input("Enter your choice: ").lower()

        if main_choice in ['1', 'login']:
            while True:
                email = input("Enter your email: ")
                if not is_valid_email(email):
                    print("Invalid email format. Please try again or type 'exit' to return to main menu.")
                    if email.lower() == 'exit':
                        break
                    continue

                user = login(conn, email)
                if user:
                    while True:
                        password = getpass.getpass("Enter your password: ")
                        if user[1] == password:
                            print(f"Welcome back, {user[2]}!")
                            main_menu(conn, user[0])
                            break  # Exit password loop after successful login
                        else:
                            print("Incorrect password. Please try again or type 'exit' to return to main menu.")
                            if password.lower() == 'exit':
                                break
                    break  # Exit email loop after successful login or exit from password loop
                else:
                    print("Account does not exist. Please try again or type 'exit' to return to main menu.")
                    user_input = input().lower()
                    if user_input == 'exit':
                        break

        elif main_choice in ['2', 'signup']:
            while True:
                email = input("Enter your email: ")
                if email.lower() == 'exit':
                    break
                if not is_valid_email(email):
                    print("Invalid email format. Please try again or type 'exit' to return to main menu.")
                    continue

                if signup(conn, email):
                    print("Signup successful. You can now log in.")
                    main_menu(conn, email)  # Users proceed to main menu after signup
                    break  # Exit signup loop after successful signup
                else:
                    print("Signup failed. Please try again or type 'exit' to return to main menu.")

        elif main_choice in ['3', 'exit']:
            print("Exiting the program.")
            break  # Exit the main loop and close the application

        else:
            print("Invalid choice, please try again.")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <database_name.db>")
        sys.exit(1)
    main(sys.argv[1])
