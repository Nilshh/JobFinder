FROM nginx:alpine
COPY jobfinder.html /usr/share/nginx/html/index.html
EXPOSE 80
