"""Launch the review-first app with the Week 5 refined detector option.

Run: python -m streamlit run week5/app.py
"""

# The mature review/correct/export UI remains in one implementation.  Week 5
# extends its detector selector without forking the safety and audit logic.
import week4.app as review_app

# Set on the module (not via PBL_APP_VERSION) so a reused process still shows Week 5.
review_app.APP_VERSION = "Week 5"
review_app.main()
