cmake_minimum_required(VERSION 3.8)
project(puppypi_vendor)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY puppypi_control
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
