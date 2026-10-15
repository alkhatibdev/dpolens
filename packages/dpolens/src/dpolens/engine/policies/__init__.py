"""Organisation policies: reading a Word or Markdown file into a tree of clauses.

Nothing here guesses silently and no model builds the tree. A reader turns the file into
paragraphs and tables with every signal they carry; the layers decide the tree from the
file's own structure, then its typography, then the numbers typed into its text; the checks
prove that every character landed somewhere; and whatever the layers could not settle
becomes a flag for the person reviewing the draft.
"""
