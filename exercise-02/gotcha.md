Claude was just giving an introductory overview of the system and made the
following set of claims:

> search() (app.js:39-66) reads whatever's in the search box (empty string on first load), calls api.searchMovies(query), and for each row returned builds a `<tr>` by hand with template strings and appends it to the results table. It also attaches a click handler to each row that calls showMovie(title).

So I asked:

> Have I found my required mistake already?? You say "search() (app.js:39-66) reads whatever's in the search box (empty string on first load)". But both times I have gotten the program running and loaded <http://localhost:8080/>, it has prepopulated the search box with "Matrix". Explain.

And received the reply:

> Yes — that's a legitimate catch. I was wrong.
>
> src/assets/index.html:21:
> `<input type="text" value="Matrix" placeholder="Search for Movie Title" class="form-control" name="search">`
>
> The input has value="Matrix" hardcoded in the markup. So on page load, $("#search").find("input[name=search]").val() (app.js:40) returns "Matrix", not "". My claim that it reads "whatever's in the search box (empty string on first load)" was wrong on the second half — I described the mechanism correctly (it does read whatever's currently in the box) but asserted a specific value without having actually looked at the HTML to check what that value defaults to. I inferred "empty" from habit/assumption about how search boxes usually start, not from evidence.
> 
> That's exactly the kind of thing gotcha.md wants: my claim, the file/line that contradicts it (index.html:21), and how you caught it (running the app and observing the actual behavior, then checking source to confirm).

…and sure enough, line 21 in the specified file is as described.  It just entirely confabulated this empty-string business.  Which seems a bit concerning, right?  I was expecting to have to look a lot harder to find something it made up, but this was, like, basically in the first five minutes of poking around.
