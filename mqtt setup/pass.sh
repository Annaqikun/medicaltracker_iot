touch passwordfile

mosquitto_passwd -c passwordfile coordinator
# Enter password: 1234
# Add more users
mosquitto_passwd -b passwordfile rpi 1234
mosquitto_passwd -b passwordfile pico_1 pico123
mosquitto_passwd -b passwordfile dashboard dash123
