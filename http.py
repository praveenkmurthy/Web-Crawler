#!/usr/bin/python

from bs4 import BeautifulSoup
import urllib
import socket
import zlib
import sys
import re
import Queue
import time

class HTTPConnection():
    """ contains all the methods
        related to handling HTTP Protocol """

    hostPort = 80
    get = "GET"
    post = "POST"
    httpVersionTag = "HTTP/1.1"
    bufferSize = 8192
    targetDomain = "fring.ccs.neu.edu"

    staticRequestFields = {"Host":"fring.ccs.neu.edu", \
                            "Connection":"keep-alive", \
                            "Accept":"text/html", \
                            "Accept-Encoding":"gzip", \
                            "Accept-Language":"en-US"}

    optionalRequestFields = {"Content-Type":"application/x-www-form-urlencoded", \
                             "Content-Length":"", \
                             "Cookie":""}

    def __init__(self, hostName, username, password):
        """ initializes TCP connection
            Exits if failed to open connection"""

        self.hostName = hostName
        self.cookieDB = {}
        self.response = ''
        self.processedRequest = 0
        self.username = username
        self.password = password

    def connect(self):
    	try:
            self.socketHandle = socket.create_connection((self.hostName, self.__class__.hostPort))
        except Exception as e:
            print "ERROR: Failed to connect to server: %s - %s" % (hostName, e)
            sys.exit(1)

        htmlResponse = self.execGetRequest("/fakebook/", "")

        postCommandInfo={}
        postCommandInfo["username"] = self.username
        postCommandInfo["password"] = self.password
        soup = BeautifulSoup(htmlResponse, "html.parser")
        [postCommandInfo.update({k.get("name") : k.get("value")}) for k in soup.findAll('input') if k.get("name") == "csrfmiddlewaretoken" or k.get("name") == "next"]

        return self.execPostRequest("/accounts/login/", urllib.urlencode(postCommandInfo))

    def close(self):
    	self.socketHandle.close()

    def __socketSend(self, buffer, size):
        """ Sends the complete buffer to server """
        totalsent = 0
        while totalsent < size:
            try:
                sent = self.socketHandle.send(buffer[totalsent:])
            except Exception, e:
                print "Error: Failed to Send to server: %s - %s" % (self.hostName, e)
                sys.exit(1)
            else:
                if sent == 0:
                    raise AssertionError("Connection Closed")
                totalsent += sent

    def __socketReceive(self, size=bufferSize):
        """ Receives atleast one response with all the headers """
        chunks = []
        response = ''
        while not re.search(r'\n\r\n', response) and not re.search(r'\r\n0\r\n\r\n', response) and size > 0:
            try:
                response = self.socketHandle.recv(min(size, self.__class__.bufferSize))
            except Exception, e:
                print "Error: Failed to receive data from server: %s - %s" % (self.hostName, e)
                sys.exit(1)
            else:
                if len(response) == 0:
                    raise AssertionError("Connection Closed")
                chunks.append(response)
                size -= len(response)

        return ''.join(chunks)

    def __buildCommandHeader(self, command, url, contentLength):
        """ Builds the HTTP Command Header fields """

        httpCommand = "%s\r\n%s\r\n" % (" ".join([command, url, self.__class__.httpVersionTag]), \
                                "\r\n".join("%s: %s" % (k,v) for k,v in self.__class__.staticRequestFields.items()))

        for k,v in self.__class__.optionalRequestFields.items():
            if k == "Cookie" and len(self.cookieDB):
                httpCommand += "Cookie: %s\r\n" % ("; ".join("%s=%s" % (k,v) for k,v in self.cookieDB.items()))
            elif k == "Content-Type" and contentLength:
                httpCommand += "%s: %s\r\n" % (k,v)
            elif k == "Content-Length" and contentLength:
                httpCommand += "%s: %d\r\n" % (k, contentLength)

        return "%s\r\n" % (httpCommand)

    def __executeRequest(self, command):
        """ Executes the given command & returns the reply """

        htmlBody = ''

        self.__socketSend(command, len(command))

        recvSize = self.__class__.bufferSize
        while not self.processedRequest :
            self.response += self.__socketReceive(recvSize)
            (htmlBody, recvSize) = self.handleResponse(self.response[self.response.find(self.__class__.httpVersionTag):])

        self.processedRequest = 0
        self.response = ""
        return htmlBody

    def execGetRequest(self, url, body):
        """ Executes HTTP GET Request with the given url
            Returns the html body of successful response/ error response"""

        return self.__executeRequest((self.__buildCommandHeader(self.__class__.get, url, len(body)) + body))


    def execPostRequest(self, url, body):
        """ Executes HTTP POST Request with the given url & body
            Returns the html body of successful response/ error response"""

        return self.__executeRequest((self.__buildCommandHeader(self.__class__.post, url, len(body)) + body))


    def execHeadRequest(self, url):
        """ Executes HTTP HEAD Request with the given url
            Returns the html body of successful response/ error response"""

        pass

    def handleResponse(self, response):
        """ Handles HTTP RESPONSES """

        self.__handleCookie(response)

        responseHandlerFunction = "handle"+ response[len(self.__class__.httpVersionTag)+1] +"xx"
        if hasattr(self.__class__, responseHandlerFunction):
            return getattr(self.__class__, responseHandlerFunction)(self, response)
        else:
            print "Unknown Function: %s" % responseHandlerFunction
            sys.exit(1);

    def handle1xx(self, response):
        """ Handles 1xx responses from server """
        self.response = ''
        return ('', self.__class__.bufferSize)

    def handle2xx(self, response):
        """ Handles 2xx responses from server """

        return self.__processResponse(response)        

    def handle3xx(self, response):
        """ Handles 3xx responses from server """

        redirectedURL = "".join("%s" % (k[10:-1]) for k in response.split("\n") if k.split(':')[0] == "Location")
        redirectedURL = re.search(self.__class__.targetDomain, redirectedURL) and redirectedURL.split(".edu")[1] or redirectedURL

        getCommand = self.__buildCommandHeader(self.__class__.get, redirectedURL, 0)
        self.__socketSend(getCommand, len(getCommand))
        self.response = ''
        return ('', self.__class__.bufferSize)

    def handle4xx(self, response):
        """ Handles 4xx responses from server """

        (htmlErrorContent, recvSize) = self.__processResponse(response)

        if htmlErrorContent:
        	print "Client Error: %s" % (htmlErrorContent)
        	sys.exit(1)

        return (htmlErrorContent, recvSize)

    def handle5xx(self, response):
        """ Handles 5xx responses from server """
        (htmlErrorContent, recvSize) = self.__processResponse(response)

        if htmlErrorContent:
        	raise AssertionError("5xx Error Response received!!")

        return (htmlErrorContent, recvSize)

    def __processResponse(self, response):
        """ Process the response """
        contentLength = 0
        chunkedResponse = False
        compressedHtmlBody = False
        pendingSize = self.__class__.bufferSize


        """ Extract HTML Body """
        htmlBody = response.split("\n\r\n")[1]

        pattern = re.compile('(.*): (.*)\r\n')

        for k,v in pattern.findall(response):
            if k.lower().find("content-length") != -1:
                contentLength = int(v)
            elif k.lower().find("transfer-coding") != -1 and v.lower().find("chunked") != -1:
                chunkedResponse = True
            elif k.lower().find("content-encoding") != -1 and v.lower().find("gzip") != -1 :
                compressedHtmlBody = True

        if contentLength:
            if contentLength == len(htmlBody):
                self.processedRequest = 1
                htmlBody = self.__handleNormalResponse(htmlBody, compressedHtmlBody)
            else:
                print "Not Received complete body to process"
                htmlBody = ''
                pendingSize = contentLength - len(htmlBody)
        elif chunkedResponse:
        	if response.search(r'\r\n0\r\n\r\n'):
        		self.processedRequest = 1
        		htmlBody = self.__handleChunkedResponse(htmlBody, compressedHtmlBody)
        	else:
        		print "Not Received complete response to process"
        		htmlBody = ''

        return (htmlBody, pendingSize)

    def __handleCookie(self, response):
        """ Handles Cookie states """
        """ Update Cookie DB """
        pattern = re.compile('(.*): ((\w*)=(\w*; ))')

        for k,v,cookie,cookieValue in pattern.findall(response):
            if k.lower() == "set-cookie":
                self.cookieDB[cookie] = cookieValue[:-2]

    def __handleNormalResponse(self, htmlBody, isResponseCompressed):
        """ Handles 2xx responses from server """

        if isResponseCompressed:
        	htmlBody = self.__handleGzipBody(htmlBody)

        return htmlBody        

    def __handleChunkedResponse(self, htmlBody, isResponseCompressed):
        """ Handles Chunked Data """
        
        combinedHtmlString = ''
        pattern = re.compile('(.*)\r\n(.*)\r\n')

        for length, data in pattern.findall(htmlBody):
        	combinedHtmlString += self.__handleGzipBody(data)

        return combinedHtmlString

    def __handleGzipBody(self, body):
        """ Handles the compressed response
            Returns the uncompressed response """
        return zlib.decompress(body, 16+zlib.MAX_WBITS)


if __name__ == "__main__" :
    if len(sys.argv) < 3:
    	print "Usage: python http.py <username> <password>"
    	sys.exit(1)

    httpCon = HTTPConnection("fring.ccs.neu.edu", sys.argv[1], sys.argv[2])
    mainPage = httpCon.connect()

    frontierLinks = Queue.Queue()
    visitedLinks = ["/fakebook/", "/accounts/login/"]
    currentPageLinks = []
    secretFlags = []

    soup = BeautifulSoup(mainPage, "html.parser")
    [secretFlags.append(k) for k in soup.findAll('h2', { "class" : "secret_flag" }) if not (k in secretFlags)]
    currentPageLinks = [k.get("href") for k in soup.findAll("a") if ((k.get("href").find("www.") == -1) and (k.get("href")[0] == '/')) or (k.get("href").find("fring.ccs.neu.edu") != -1)] 
    [frontierLinks.put(k) for k in currentPageLinks if not (k in visitedLinks)]
    #print "FrontierQueue Size: %d No.Of SecretFlags : %d currentPageLinks : %d" % (frontierLinks.qsize(), len(secretFlags), len([k for k in currentPageLinks if not (k in visitedLinks)]))

    while not frontierLinks.empty():
    	if len(secretFlags) == 5:
    		break

    	del currentPageLinks[:]
    	linkToVisit = frontierLinks.get()

    	try:
    		htmlResponse = httpCon.execGetRequest(linkToVisit, "")
    	except AssertionError, e:
    		frontierLinks.put(linkToVisit)
    		httpCon.close()
    		httpCon = HTTPConnection("fring.ccs.neu.edu", sys.argv[1], sys.argv[2])
    		httpCon.connect()
    		continue
    	
    	visitedLinks.append(linkToVisit)

    	soup = BeautifulSoup(htmlResponse, "html.parser")

    	[secretFlags.append(k) for k in soup.findAll('h2', { "class" : "secret_flag" }) if not (k in secretFlags)]
    	currentPageLinks = [k.get("href") for k in soup.findAll("a") if ((k.get("href").find("www.") == -1) and (k.get("href")[0] == '/')) or (k.get("href").find("fring.ccs.neu.edu") != -1)] 
    	[frontierLinks.put(k) for k in currentPageLinks if not (k in visitedLinks)]
    	#print "FrontierQueue Size: %d No.Of SecretFlags : %d currentPageLinks : %d" % (frontierLinks.qsize(), len(secretFlags), len([k for k in currentPageLinks if not (k in visitedLinks)]))

    print "\n".join(["%s" % (k.string) for k in secretFlags])
    	
    sys.exit(0)
