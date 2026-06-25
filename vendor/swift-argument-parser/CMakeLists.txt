cmake_minimum_required(VERSION 3.19)

# Due to a bug in CMake, we need to enable the C language before we can use
# GNUInstallDirs.
project(swift-argument-parser
  LANGUAGES C Swift)

option(BUILD_EXAMPLES "Build Example Programs" TRUE)
option(BUILD_SHARED_LIBS "Build shared libraries by default" YES)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake/modules)

set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

set(CMAKE_Swift_MODULE_DIRECTORY ${CMAKE_BINARY_DIR}/swift)

include(CTest)

include(GNUInstallDirs)
include(SwiftSupport)

if(NOT APPLE)
  find_package(dispatch CONFIG)
  find_package(Foundation CONFIG)
  if(BUILD_TESTING)
    find_package(XCTest CONFIG)
  endif()
endif()

add_subdirectory(Sources)
if(BUILD_EXAMPLES AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/Examples")
  add_subdirectory(Examples)
endif()
if(BUILD_TESTING AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/Tests")
  add_subdirectory(Tests)
endif()

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/cmake/modules")
  add_subdirectory(cmake/modules)
endif()
