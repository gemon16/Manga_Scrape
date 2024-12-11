from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import re
import os
import requests
from PIL import Image, UnidentifiedImageError
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


def get_image_urls(url_list, page_limit=None, retries=5, wait_time=4, min_images=10):
    driver = None  # Initialize driver outside the loop
    all_image_data = {}  # Dictionary to store image data
    error_log = []  # To store URLs and their error codes
    pages_processed = 0  # Counter for processed pages

    try:
        driver = get_driver_with_options()  # Start the driver once initially

        for url in url_list:
            if page_limit is not None and pages_processed >= page_limit:
                print(f"Page limit of {page_limit} reached. Stopping.")
                break

            print(f"Checking URL: {url}")
            retries_left = retries  # Set the initial retry count

            while retries_left > 0:
                try:
                    found_sufficient_images = False

                    for server in range(1, 5):  # Attempt up to 4 servers
                        server_url = url.replace("server-1", f"server-{server}")
                        driver.get(server_url)
                        print(f"Loading page: {server_url}")

                        WebDriverWait(driver, 3).until(
                            EC.presence_of_all_elements_located((By.TAG_NAME, "img"))
                        )
                        print(f"Page {server_url} loaded.")

                        image_tags = driver.find_elements(By.CSS_SELECTOR, "img.w-full.h-full")

                        if not image_tags:
                            print(f"No images found on {server_url}. Trying next server...")
                            continue

                        image_src_urls = [img.get_attribute("src") for img in image_tags]

                        if len(image_src_urls) >= min_images:
                            print(f"Found {len(image_tags)} images on {server_url}.")
                            all_image_data[url] = image_src_urls[:160]  # Limit to 160 images per URL
                            pages_processed += 1
                            found_sufficient_images = True
                            break  # Exit server loop if successful
                        else:
                            print(f"Only {len(image_src_urls)} images found on {server_url}. Trying next server...")

                    if found_sufficient_images:
                        break  # Exit retry loop if images are found
                    else:
                        print(f"Failed to find enough images on all servers for {url}.")
                        error_log.append({"url": url, "error_code": "INSUFFICIENT_IMAGES"})
                        all_image_data[url] = []  # Add empty list for consistency
                        break  # Exit retry loop

                except Exception as e:
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

    return all_image_data, {"image_data": all_image_data, "errors": error_log}




def extract_and_sort(data):
    """
    Sort a list or dictionary based on embedded volume, chapter, episode, or prologue in each string.
    Recognizes 'volume-##-episode-###', 'volume-##-prologue-###', 'vol-##-ch-###', and 'ch-###' patterns,
    sorting accordingly. Logs all unmatched keys at the end.
    """
    unmatched_keys = []  # List to store unmatched keys

    def sort_key(link):
        # Match 'volume-##-prologue-###'
        match_prologue = re.search(r'volume-(\d+)-prologue-(\d+)', link.lower())
        if match_prologue:
            vol = int(match_prologue.group(1))
            prologue = int(match_prologue.group(2))
            print(f"Matched volume-{vol}-prologue-{prologue} for key: {link}")
            return (vol, 0, prologue, 0)  # Prologue is prioritized (comes before episodes)

        # Match 'volume-##-episode-###'
        match_episode = re.search(r'volume-(\d+)-episode-(\d+)', link.lower())
        if match_episode:
            vol = int(match_episode.group(1))
            episode = int(match_episode.group(2))
            print(f"Matched volume-{vol}-episode-{episode} for key: {link}")
            return (vol, 1, episode, 0)  # Episode comes after prologue

        # Match 'vol-##-ch-###'
        match_chapter = re.search(r'vol-(\d+)-ch-(\d+)', link.lower())
        if match_chapter:
            vol = int(match_chapter.group(1))
            ch = int(match_chapter.group(2))
            print(f"Matched vol-{vol}-ch-{ch} for key: {link}")
            return (vol, 2, ch, 0)  # Chapters come after episodes

        # Match 'ch-###' (standalone chapter)
        match_standalone_ch = re.search(r'ch-(\d+)', link.lower())
        if match_standalone_ch:
            ch = int(match_standalone_ch.group(1))
            print(f"Matched ch-{ch} for key: {link}")
            return (float('inf'), ch, 0, 0)  # Standalone chapters come last

        # Log unmatched link
        unmatched_keys.append(link)
        print(f"No match for link: {link}")
        return (float('inf'), float('inf'), float('inf'), float('inf'))

    if isinstance(data, list):
        # Filter out invalid links
        filtered_data = [
            link for link in data 
            if re.search(r'(volume-\d+-(episode|prologue)-\d+|vol-\d+-ch-\d+|ch-\d+)', link.lower())
        ]
        # Sort the filtered list
        sorted_data = sorted(filtered_data, key=sort_key)

    elif isinstance(data, dict):
        # Filter out invalid links in dictionary keys
        filtered_data = {
            k: v for k, v in data.items()
            if re.search(r'(volume-\d+-(episode|prologue)-\d+|vol-\d+-ch-\d+|ch-\d+)', k.lower())
        }
        # Sort the filtered dictionary
        sorted_keys = sorted(filtered_data.keys(), key=sort_key)
        sorted_data = {k: filtered_data[k] for k in sorted_keys}

    else:
        raise TypeError("Input must be a list or dictionary.")

    # Print all unmatched keys
    if unmatched_keys:
        print("\nUnmatched Keys:")
        for key in unmatched_keys:
            print(key)

    return sorted_data


def download_manga_images(image_data, manga_name):
    """
    Downloads images for a manga into structured folders based on volume and chapter/episode/prologue,
    prioritizing prologues over episodes within the same volume.

    Parameters:
        image_data (dict): A dictionary where keys are URLs with recognized patterns such as
                           'volume-##-episode-###', 'volume-##-prologue-###', 'vol-##-ch-###', or 'ch-###',
                           and values are lists of image URLs to download.
        manga_name (str): The name of the manga, used as the main folder name.

    Returns:
        None
    """
    # Create the main folder for the manga
    main_folder = os.path.join(os.getcwd(), manga_name)
    os.makedirs(main_folder, exist_ok=True)

    # Sort the image_data keys using the same logic as extract_and_sort
    sorted_urls = sorted(image_data.keys(), key=lambda url: (
        int(re.search(r'volume-(\d+)', url.lower()).group(1)) if re.search(r'volume-(\d+)', url.lower()) else float('inf'),
        0 if re.search(r'prologue', url.lower()) else 1,
        int(re.search(r'(episode|prologue|ch)-(\d+)', url.lower()).group(2)) if re.search(r'(episode|prologue|ch)-(\d+)', url.lower()) else float('inf')
    ))

    for url in sorted_urls:
        image_urls = image_data[url]
        # Extract details based on patterns
        match_prologue = re.search(r'volume-(\d+)-prologue-(\d+)', url.lower())
        match_episode = re.search(r'volume-(\d+)-episode-(\d+)', url.lower())
        match_chapter = re.search(r'vol-(\d+)-ch-(\d+)', url.lower())
        match_standalone_ch = re.search(r'ch-(\d+)', url.lower())

        if match_prologue:
            vol = match_prologue.group(1)
            prologue = match_prologue.group(2)
            subfolder_name = f"volume-{vol}-prologue-{prologue}"
        elif match_episode:
            vol = match_episode.group(1)
            episode = match_episode.group(2)
            subfolder_name = f"volume-{vol}-episode-{episode}"
        elif match_chapter:
            vol = match_chapter.group(1)
            ch = match_chapter.group(2)
            subfolder_name = f"vol-{vol}-ch-{ch}"
        elif match_standalone_ch:
            ch = match_standalone_ch.group(1)
            subfolder_name = f"ch-{ch}"
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
    If any unreadable images are encountered, the source folder is not deleted.
    
    Parameters:
        manga_folder (str): The root folder containing subfolders with images.
    
    Returns:
        None
    """
    if not os.path.exists(manga_folder):
        print(f"Error: The specified folder '{manga_folder}' does not exist.")
        return

    error_folders = []  # List to track folders with errors or unreadable files

    # Traverse all subdirectories
    for root, dirs, files in os.walk(manga_folder, topdown=False):  # Process subfolders after their contents
        # Skip the root level; process only subfolders
        if root == manga_folder:
            continue

        # Filter and sort image files (.jpg, .jpeg, .png)
        images = sorted([f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png"))])
        valid_images = []
        folder_has_errors = False

        if images:
            for img in images:
                img_path = os.path.join(root, img)
                try:
                    # Attempt to open the image
                    image = Image.open(img_path).convert("RGB")
                    valid_images.append(image)
                except UnidentifiedImageError:
                    print(f"Skipped unreadable or corrupt image: {img_path}")
                    folder_has_errors = True
                except Exception as e:
                    print(f"Error processing image '{img_path}': {e}")
                    folder_has_errors = True

            if valid_images:
                try:
                    # Define the PDF output path in the main folder
                    pdf_filename = os.path.join(manga_folder, os.path.basename(root) + ".pdf")
                    
                    # Save the valid images as a single PDF
                    valid_images[0].save(pdf_filename, save_all=True, append_images=valid_images[1:])
                    print(f"Converted images in '{root}' to '{pdf_filename}'")

                    # Delete files and folder only if there are no errors
                    if not folder_has_errors:
                        try:
                            for f in files:
                                file_path = os.path.join(root, f)
                                os.remove(file_path)
                            os.rmdir(root)
                            print(f"Deleted subfolder '{root}', leaving only '{pdf_filename}' in the main folder")
                        except Exception as e:
                            print(f"Error deleting folder or files in '{root}': {e}. Folder not deleted.")
                    else:
                        error_folders.append(root)
                        print(f"Folder '{root}' contains errors or unreadable files. Not deleted.")
                except Exception as e:
                    print(f"Error saving PDF for '{root}': {e}")
                    error_folders.append(root)
            else:
                print(f"No valid images found in '{root}'. Skipping PDF creation.")
                error_folders.append(root)
        else:
            print(f"No valid images found in '{root}'. Skipping...")
            error_folders.append(root)

    # Summary of folders with errors
    if error_folders:
        print("\nSummary: The following folders contained errors or unreadable files and were not deleted:")
        for folder in error_folders:
            print(f" - {folder}")
    else:
        print("\nAll folders processed successfully without errors.")


def reorder_files_in_place(folder_name):
    """
    Reorder files in the same folder based on:
    1. Volume numbers ('vol-XX')
    2. Priority ('prologue' first, 'episode' second)
    3. Chapter/Episode/Prologue numbers ('ch-###', 'episode-###', 'prologue-###')
    
    Renames files in-place by adding numerical prefixes to enforce order.

    Parameters:
        folder_name (str): Name of the folder to process.

    Returns:
        None: Files are renamed in the folder in the correct order.
    """
    folder_path = os.path.abspath(folder_name)
    if not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Folder '{folder_name}' not found.")
    
    def extract_sort_key(filename):
        """
        Extract volume, priority (prologue or episode), and number from the filename.
        Returns a tuple (volume, priority, number).
        """
        volume_match = re.search(r'vol-(\d+)', filename, re.IGNORECASE)
        prologue_match = re.search(r'prologue-(\d+)', filename, re.IGNORECASE)
        episode_match = re.search(r'episode-(\d+)', filename, re.IGNORECASE)
        chapter_match = re.search(r'ch-(\d+)', filename, re.IGNORECASE)

        volume = int(volume_match.group(1)) if volume_match else float('inf')
        if prologue_match:
            priority = 0  # Prologue comes first
            number = int(prologue_match.group(1))
        elif episode_match:
            priority = 1  # Episode comes second
            number = int(episode_match.group(1))
        elif chapter_match:
            priority = 2  # Chapter comes last
            number = int(chapter_match.group(1))
        else:
            priority = float('inf')  # Files with no recognizable pattern go last
            number = float('inf')

        return volume, priority, number

    # Get a list of files in the folder
    files = os.listdir(folder_path)

    # Build a list of tuples: ((volume, priority, number), original_filename)
    file_data = []
    for file in files:
        sort_key = extract_sort_key(file)
        file_data.append((sort_key, file))

    # Sort by volume, priority, and number
    sorted_files = sorted(file_data, key=lambda x: x[0])

    # Rename files in place with numerical prefixes
    for i, ((volume, priority, number), filename) in enumerate(sorted_files):
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
url = "https://mangapark.io/title/219752-en-berserk"
keyword = "Berserk"
manga_title = 'Berserk - Kentaro Miura'
links = get_manga_links(url, keyword,page_limit=2)

# %%
ordered = extract_and_sort(links)
# %%

errors=['https://mangapark.io/title/219752-en-berserk/8937480-volume-1-prologue-1','https://mangapark.io/title/219752-en-berserk/8937506-volume-1-prologue-2']
# %%
image_urls,error_log = get_image_urls(errors)

#%%
download_manga_images(image_urls, manga_title)
#This might look sorta wonky but order will be correct once we get to reorder file in place
# %%
convert_chapter_pdfs(manga_folder=manga_title)
# %%
reorder_files_in_place(manga_title)


# %%
append_pdfs_to_manga_collection(input_folder=manga_title)






