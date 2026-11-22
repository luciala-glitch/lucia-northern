# Week 7 demo

From the project folder, run `python -m streamlit run week7/app.py`. The [README](README.md) lists the dependencies.

## What I’ll show

1. Choose **DENPAR-TEST-68**. Leave **Include simulated corrections** on. This X-ray has four teeth. The original image is on the left. The marked image is on the right.
2. Select **T4**. The model gave this tooth 31.2% PBL, or Stage II. Look at the distal CEJ and the distal bone crest. I used the reference points to simulate an edit to those two landmarks.
3. Look at the two readings for T4. The distal side now gives 35.0%. That crosses the 33% cutoff for Stage III/IV. The report shows both readings.
4. To try an edit, change the apex y coordinate for T4. Type your name under **Reviewer name or ID** and save. Look for your name in the history. The simulated edit is still there.
5. Open the PDF to see the image and tooth table. The CSV has one row per tooth. The JSON keeps the points and edit history.

## Other things to try

- Turn off simulated corrections. The highest stage for this case drops to II.
- Choose **Discard my edits for this case**. Check the tooth labels before confirming.
- Open **EDGE-one-surface**. T2 has no distal crest. The mesial side gives a minimum of Stage II.
- Open **DENPAR-TEST-100** and look at T1. The model gave it Stage III/IV with 99% stage support. The reference was Stage I. The review rule missed it.

I still want to check the tooth close-up on a shared screen and try the JSON file picker in a browser.
