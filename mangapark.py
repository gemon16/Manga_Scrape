from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import re
import os
import requests
from PIL import Image
import pikepdf
import time

def get_driver_with_options():
    # Create ChromeOptions
    chrome_options = Options()
    
    # Path to the uBlock Origin extension
    app_folder = os.path.dirname(os.path.abspath(__file__))  # Get the folder of the current script
    ublock_extension_path = os.path.join(app_folder, "extensions", "ublock")  # Adjust path if needed
    
    # Add Chrome options
    chrome_options.add_argument("--headless")  # Uncomment if headless mode is desired
    chrome_options.add_argument("--disable-popup-blocking")  # Disable pop-up blocking
    chrome_options.add_argument("--incognito")  # Incognito mode (optional)
    
    # Additional arguments to bypass extension verification and security checks
    chrome_options.add_argument("--no-sandbox")  # Disable sandboxing
    chrome_options.add_argument("--disable-web-security")  # Disable web security for extensions
    chrome_options.add_argument("--disable-extensions-file-access-check")  # Allow loading unpacked extensions
    chrome_options.add_argument("--allow-running-insecure-content")  # Allow insecure content
    chrome_options.add_argument("--disable-features=ComponentUpdater")  # Disable the component updater entirely
    
    # Add the uBlock Origin extension
    chrome_options.add_argument(f"--load-extension={ublock_extension_path}")
    
    # Initialize the Chrome driver with options
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Failed to initialize the Chrome driver: {e}")
        raise



def get_manga_links(url, manga_title, page_limit=None):
    """
    Scrape links from a webpage containing the specified manga title, up to a page limit.
    
    Parameters:
        url (str): The URL of the webpage to scrape.
        manga_title (str): The title of the manga to search for in the links.
        page_limit (int, optional): Maximum number of links to scrape. Default is None (unlimited).
        
    Returns:
        set: A set of unique links (hrefs) that contain the specified manga title.
    """
    # Initialize the Selenium WebDriver
    driver = get_driver_with_options()
    filtered_hrefs = set()

    try:
        # Open the target URL
        driver.get(url)

        # Wait for the page content to load and get all links with an href attribute
        WebDriverWait(driver, 3).until(
            EC.presence_of_all_elements_located((By.XPATH, "//a[@href]"))
        )

        # Find all elements with an href attribute
        elements = driver.find_elements(By.XPATH, "//a[@href]")

        # Get all hrefs at once
        hrefs = [element.get_attribute("href") for element in elements]

        # Filter hrefs containing the manga title and 'vol' or 'ch'
        page_hrefs = [
            href for href in hrefs
            if manga_title.lower() in href.lower() 
            and ('vol' in href.lower() or 'ch' in href.lower())
        ]

        filtered_hrefs.update(page_hrefs)

        # Check if we've reached the page limit
        if page_limit and len(filtered_hrefs) >= page_limit:
            print(f"Reached page limit of {page_limit} links.")
            return set(list(filtered_hrefs)[:page_limit])

    finally:
        # Close the browser
        driver.quit()

    # Return all unique links found
    return list(filtered_hrefs)


def get_image_urls(url_list, page_limit=None, retries=5, wait_time=3):
    driver = None  # Initialize driver outside the loop
    all_image_data = {}  # Dictionary to store image data
    error_log = []  # To store URLs and their error codes
    pages_processed = 0  # Counter for processed pages

    try:
        driver = get_driver_with_options()  # Start the driver once initially

        for url in url_list:
            # Stop if we've reached the page limit
            if page_limit is not None and pages_processed >= page_limit:
                print(f"Page limit of {page_limit} reached. Stopping.")
                break
            
            print(f"Checking URL: {url}")  # Print the URL every time it checks
            retries_left = retries  # Set the initial retry count

            while retries_left > 0:
                try:
                    driver.get(url)
                    
                    # Wait for the page to load completely and for images to be present
                    print(f"Loading page: {url}")
                    WebDriverWait(driver, 3).until(
                        EC.presence_of_all_elements_located((By.TAG_NAME, "img"))
                    )
                    print(f"Page {url} loaded.")
                    
                    # Locate all img tags with the specified class across the entire page
                    image_tags = driver.find_elements(By.CSS_SELECTOR, "img.w-full.h-full")
                    
                    if not image_tags:
                        # If no images are found, log an error and retry
                        print(f"No images found on {url}. Retrying...")
                        retries_left -= 1
                        if retries_left > 0:
                            print(f"Retrying {url} ({retries_left} retries left)...")
                            time.sleep(wait_time)  # Wait before retrying
                            continue
                        else:
                            error_log.append({"url": url, "error_code": "NO_IMAGES_FOUND"})
                            all_image_data[url] = []  # Add empty list for consistency
                            break  # Exit the retry loop after the max retries
                    else:
                        # Found images, process them
                        print(f"Found {len(image_tags)} images with the specified class on {url}.")
                        image_src_urls = [img.get_attribute("src") for img in image_tags]
                        all_image_data[url] = image_src_urls[:160]  # Limit to 160 images per URL
                        pages_processed += 1
                        break  # Exit the retry loop once successful
                except Exception as e:
                    # Reinitialize driver if there is an error
                    print(f"Error processing {url}: {e}")
                    retries_left -= 1
                    if retries_left > 0:
                        print(f"Reinitializing driver and retrying {url} ({retries_left} retries left)...")
                        if driver:
                            driver.quit()  # Close the existing driver
                        driver = get_driver_with_options()  # Reinitialize the driver
                        time.sleep(wait_time)  # Wait before retrying
                    else:
                        print(f"Failed to process {url} after {retries} retries.")
                        error_log.append({"url": url, "error_code": "PAGE_LOAD_ERROR", "details": str(e)})
                        all_image_data[url] = []  # Add empty list for consistency
                        break  # Exit the retry loop after the max retries

    finally:
        if driver:
            driver.quit()  # Ensure the driver is closed at the end

    return all_image_data,{"image_data": all_image_data, "errors": error_log}




def extract_and_sort(data):
    """
    Sort a list or dictionary based on the volume and chapter numbers embedded in each string.
    Entries with 'vol-00' and 'ch-000' are excluded from the output.

    Parameters:
        data (list | dict): A list of strings or a dictionary where keys may contain 'vol-##-ch-###' patterns.

    Returns:
        list | dict: A new list or dictionary sorted by (ch, vol) extracted from the keys or list entries,
                     excluding 'vol-00-ch-000' and 'ch-000' entries.
    """
    # Check input type
    input_type = type(data)
    if not isinstance(data, (list, dict)):
        raise TypeError("Input must be either a list or a dictionary.")
    
    def sort_key(link):
        # Extract 'vol-##-ch-###' pattern
        match = re.search(r'vol-(\d+)-ch-(\d+)', link)
        if match:
            vol, ch = int(match.group(1)), int(match.group(2))
            print(f"Matched vol-{vol}-ch-{ch} for key: {link}")  # Debug
            return (ch, vol)  # Sort by chapter, then volume

        # Extract 'ch-###' pattern only
        match_chapter = re.search(r'ch-(\d+)', link)
        if match_chapter:
            ch = int(match_chapter.group(1))
            print(f"Matched ch-{ch} for key: {link}")  # Debug
            return (ch, 0)  # Default volume to 0 but still sorted by chapter
        
        print(f"No match for key: {link}")  # Debug
        return (float('inf'), float('inf'))  # Non-matching entries placed at the end

    if isinstance(data, list):
        # Filter out entries with vol-00 and ch-000
        filtered_data = [
            link for link in data 
            if not re.search(r'vol-00-ch-000', link) and not re.search(r'ch-000', link)
        ]

        # Debugging: Print filtered data
        print(f"Filtered list data: {filtered_data}")

        # Sort the filtered list
        output = sorted(filtered_data, key=sort_key)

    elif isinstance(data, dict):
        # Filter out keys with vol-00 and ch-000
        filtered_data = {
            k: v for k, v in data.items()
            if not re.search(r'vol-00-ch-000', k) and not re.search(r'ch-000', k)
        }

        # Debugging: Print filtered dictionary keys
        print(f"Filtered dictionary keys: {list(filtered_data.keys())}")

        # Sort the dictionary by the keys
        sorted_keys = sorted(filtered_data.keys(), key=sort_key)
        print(f"Sorted keys: {sorted_keys}")  # Debug
        output = {k: filtered_data[k] for k in sorted_keys}

    # Check output type
    output_type = type(output)
    if input_type != output_type:
        print("Error: Output type does not match input type!")
        print(f"Input type: {input_type}, Output type: {output_type}")
        raise TypeError("Mismatch between input and output types.")
    
    return output


def download_manga_images(image_data, manga_name):
    """
    Downloads images for a manga into structured folders based on volume and chapter.

    Parameters:
        image_data (dict): A dictionary where keys are URLs with 'vol-<number>-ch-<number>'
                           or URLs matching various chapter formats, and values are lists
                           of image URLs to download.
        manga_name (str): The name of the manga, used as the main folder name.
    
    Returns:
        None
    """
    # Create the main folder for the manga
    main_folder = os.path.join(os.getcwd(), manga_name)
    os.makedirs(main_folder, exist_ok=True)

    for url, image_urls in image_data.items():
        # Extract volume and chapter from the URL
        match = re.search(r'(vol-(\d+))?-(ch-\d+(-\d+)?)', url)
        if match:
            vol = match.group(2) or "00"  # Default volume to 00 if not present
            ch = match.group(3)
            subfolder_name = f"vol-{vol}-{ch}"
        else:
            ch_match = re.search(r'ch-(\d+(-\d+)?)', url)
            if ch_match:
                ch = ch_match.group(0)
                subfolder_name = f"vol-00-{ch}"
            else:
                subfolder_name = "unknown"

        # Create the subfolder
        subfolder = os.path.join(main_folder, subfolder_name)
        os.makedirs(subfolder, exist_ok=True)

        # Download images into the subfolder
        for index, img_url in enumerate(image_urls):
            try:
                print(f"Downloading {img_url} into {subfolder}...")
                response = requests.get(img_url, stream=True)
                response.raise_for_status()

                # Save the image with a zero-padded index
                filename = os.path.join(subfolder, f"{index:03d}.jpg")
                with open(filename, "wb") as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                print(f"Saved: {filename}")
            except Exception as e:
                print(f"Failed to download {img_url}: {e}")



def convert_chapter_pdfs(manga_folder):
    """
    Converts all images in each subfolder of the given folder into a single PDF for each subfolder,
    saves the PDFs in the main folder, and deletes all subfolders and their contents after conversion.

    Parameters:
        manga_folder (str): The root folder containing subfolders with images.
    
    Returns:
        None
    """
    if not os.path.exists(manga_folder):
        print(f"Error: The specified folder '{manga_folder}' does not exist.")
        return

    # Traverse all subdirectories
    for root, dirs, files in os.walk(manga_folder, topdown=False):  # Process subfolders after their contents
        # Skip the root level; process only subfolders
        if root == manga_folder:
            continue

        # Filter and sort image files (.jpg, .jpeg, .png)
        images = sorted([f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png"))])

        if images:
            try:
                # Create a list to hold Image objects
                img_objects = [Image.open(os.path.join(root, img)).convert("RGB") for img in images]
                
                # Define the PDF output path in the main folder
                pdf_filename = os.path.join(manga_folder, os.path.basename(root) + ".pdf")
                
                # Save the images as a single PDF
                img_objects[0].save(pdf_filename, save_all=True, append_images=img_objects[1:])
                print(f"Converted images in '{root}' to '{pdf_filename}'")

                # Delete all files in the subfolder
                for f in files:
                    file_path = os.path.join(root, f)
                    os.remove(file_path)

                # Remove the now-empty subfolder
                os.rmdir(root)
                print(f"Deleted subfolder '{root}', leaving only '{pdf_filename}' in the main folder")
            except Exception as e:
                print(f"Error processing images in '{root}': {e}")
        else:
            print(f"No valid images found in '{root}'. Skipping...")

    print("All subfolders have been processed.")
    
def reorder_files_in_place(folder_name):
    """
    Reorder files in the same folder based on chapter numbers ('ch-###') first,
    and volume numbers ('vol-XX') second as a tiebreaker.
    Renames files in-place by adding numerical prefixes to enforce order.

    Parameters:
        folder_name (str): Name of the folder to process.

    Returns:
        None: Files are renamed in the folder in the correct order.
    """
    folder_path = os.path.abspath(folder_name)
    if not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Folder '{folder_name}' not found.")
    
    def extract_vol_ch(filename):
        """
        Extract volume and chapter numbers from the filename.
        Returns a tuple (chapter, volume).
        """
        chapter_match = re.search(r'ch-(\d+)', filename, re.IGNORECASE)
        volume_match = re.search(r'vol-(\d+)', filename, re.IGNORECASE)

        chapter = int(chapter_match.group(1)) if chapter_match else float('inf')
        volume = int(volume_match.group(1)) if volume_match else float('inf')

        return chapter, volume

    # Get a list of files in the folder
    files = os.listdir(folder_path)

    # Build a list of tuples: ((chapter, volume), original_filename)
    file_data = []
    for file in files:
        vol_ch_data = extract_vol_ch(file)
        if vol_ch_data[0] != float('inf'):  # Only consider files with valid chapter numbers
            file_data.append((vol_ch_data, file))

    # Sort by chapter first, then volume
    sorted_files = sorted(file_data, key=lambda x: x[0])

    # Rename files in place with numerical prefixes
    for i, ((chapter, volume), filename) in enumerate(sorted_files):
        original_path = os.path.join(folder_path, filename)
        # Add a numerical prefix to enforce order
        new_filename = f"{i+1:03d}_{filename}"
        new_path = os.path.join(folder_path, new_filename)

        # Rename the file
        os.rename(original_path, new_path)
        print(f"Renamed: {original_path} -> {new_path}")

    print(f"Files successfully reordered in place within '{folder_path}'.")


def find_or_create_manga_collection_folder(folder_name="Manga Collection"):
    """
    Finds the 'Manga Collection' folder anywhere on the computer.
    If it doesn't exist, creates it in the user's home directory.

    Parameters:
        folder_name (str): The name of the folder to find or create.

    Returns:
        str: The absolute path to the 'Manga Collection' folder.
    """
    # Traverse the file system starting from the home directory
    home_directory = os.path.expanduser("~")
    for root, dirs, _ in os.walk(home_directory):
        if folder_name in dirs:
            return os.path.join(root, folder_name)
    
    # If the folder is not found, create it in the home directory
    manga_collection_path = os.path.join(home_directory, folder_name)
    os.makedirs(manga_collection_path, exist_ok=True)
    print(f"'{folder_name}' folder not found. Created at: {manga_collection_path}")
    return manga_collection_path


def append_pdfs_to_manga_collection(input_folder="input_pdfs", collection_folder_name="Manga Collection"):
    """
    Appends all PDFs from the input folder into a single PDF file, sorted by filename order.
    Saves the merged PDF in the 'Manga Collection' folder, creating it if it doesn't exist.
    
    Parameters:
        input_folder (str): The folder containing the individual PDF files.
        collection_folder_name (str): The folder where the merged PDF will be saved.

    Returns:
        None
    """
    if not os.path.exists(input_folder):
        print(f"Error: The specified folder '{input_folder}' does not exist.")
        return
    
    # Find or create the Manga Collection folder
    collection_folder_path = find_or_create_manga_collection_folder(collection_folder_name)

    # List to hold full paths of PDFs in sorted order
    pdf_files = [
        os.path.join(input_folder, f)
        for f in sorted(os.listdir(input_folder))
        if f.lower().endswith(".pdf")
    ]

    if not pdf_files:
        print("No PDF files found in the input folder.")
        return

    print(f"Found {len(pdf_files)} PDFs. Merging them...")

    # Create a new PDF for merging
    merged_pdf = pikepdf.Pdf.new()

    # Append each PDF in sorted filename order
    for pdf_path in pdf_files:
        print(f"Appending: {os.path.basename(pdf_path)}")  # Debugging for progress tracking
        with pikepdf.open(pdf_path) as pdf_to_append:
            merged_pdf.pages.extend(pdf_to_append.pages)

    # Define the merged PDF's output path
    merged_pdf_filename = os.path.join(collection_folder_path, f"{input_folder}.pdf")

    # Save the merged PDF to the Manga Collection folder
    merged_pdf.save(merged_pdf_filename)

    print(f"All PDFs have been merged and saved to: {merged_pdf_filename}")



# %%
# Run and print the image URLs to verify output
url = "https://mangapark.io/title/25039-en-billy-bat"
manga_title = "Billy"
links = get_manga_links(url, manga_title,page_limit=None)

# %%
ordered = extract_and_sort(links)
# %%
image_urls,error_log = get_image_urls(ordered)

#%%
download_manga_images(image_urls, 'Billy Bat - Naoki Urasawa')
# %%
convert_chapter_pdfs(manga_folder='Billy Bat - Naoki Urasawa')
# %%
reorder_files_in_place('Billy Bat - Naoki Urasawa')


# %%
append_pdfs_to_manga_collection(input_folder='Billy Bat - Naoki Urasawa')






