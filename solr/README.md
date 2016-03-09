## Solr Search Provider for Reddit

The Solr search provider lets you run Reddit's search on your own Solr server.


### Quickstart

To set up your own solr instance:

```
sudo apt-get -y install solr-tomcat
sudo ln -sf /path/to/reddit/solr/schema.xml /usr/share/solr/conf
sudo service tomcat6 start
```

You should now be able to connect to Solr at http://127.0.0.1:8080

To configure reddit to use Solr for search, set the search provider to **solr**
in your .ini file along with the following configuration lines:

```
search_provider = solr
# version of solr service--versions 1.x and 4.x have been tested. 
# only the major version number matters here
solr_version = 1
# solr search service hostname or IP
solr_search_host = 127.0.0.1
# hostname or IP for link upload
solr_doc_host = 127.0.0.1
# hostname or IP for subreddit search
solr_subreddit_search_host = 127.0.0.1
# hostname or IP subreddit upload
solr_subreddit_doc_host = 127.0.0.1
# solr port (assumed same on all hosts)
solr_port = 8080
# solr4 core name (not used with Solr 1.x)
solr_core = collection1
# default batch size 
# limit is hard-coded to 1000
# set to 1 for testing
solr_min_batch = 500
# optionally, you may select your solr query parser here
# see documentation for your version of Solr
solr_query_parser = 
```

### Notes

If you build Solr from source, the default port will be 8983.

In the case that you install from packages as described here and something
else is running on port 8080, then you'll have to switch to another port...
perhaps back to 8983.

First verify that that is the case:

```
sudo fuser -v 8080/tcp
```

Edit the port in the "Connector" rule in /etc/tomcat6/server.xml to be the
port you desire. Then change the "solr_port" option in
/etc/solr/conf/scripts.conf and restart the server with

```
sudo service tomcat6 start
```

and finally update the "solr_port" in the .ini file to reflect the port
you're now using.
